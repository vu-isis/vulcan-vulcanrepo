from contextlib import contextmanager
import logging
import os
import json
import re
import zipfile
import requests

from ming import schema as S
from ming.odm import FieldProperty, ThreadLocalODMSession, session
from ming.odm.declarative import MappedClass
from pylons import tmpl_context as c
from vulcanforge.auth.schema import ACL
from vulcanforge.auth.model import User
from vulcanforge.common.model.session import repository_orm_session
from vulcanforge.common.util.filesystem import import_object, temporary_dir
from vulcanforge.visualize.model import Visualizer

from vulcanrepo.tasks import purge_hook

LOG = logging.getLogger(__name__)


class PostCommitHook(MappedClass):
    class __mongometa__:
        session = repository_orm_session
        name = 'postcommithook'

    _id = FieldProperty(S.ObjectId)
    shortname = FieldProperty(str)
    name = FieldProperty(str)
    description = FieldProperty(str, if_missing='')
    removable = FieldProperty(bool, if_missing=True)
    wants_all = FieldProperty(bool, if_missing=False)
    hook_cls = FieldProperty(S.Object({
        'module': str,
        'classname': str
    }))
    default_args = FieldProperty([None])
    default_kwargs = FieldProperty({str: None})
    acl = FieldProperty(ACL(permissions=['install', 'read']))

    @classmethod
    def upsert(cls, obj, **kwargs):
        isnew = False
        pch = cls.query.get(
            module=obj.__module__, classname=obj.__name__, **kwargs)
        if not pch:
            pch = cls.from_object(obj, **kwargs)
            isnew = True
        return pch, isnew

    @classmethod
    def from_object(cls, obj, **kwargs):
        return cls(
            hook_cls={
                "module": obj.__module__,
                "classname": obj.__name__
            },
            **kwargs)

    def delete(self):
        purge_hook.post(self._id)
        super(PostCommitHook, self).delete()

    def run(self, commits, args=(), kwargs=None):
        if not args:
            args = self.default_args
        full_kw = self.default_kwargs.copy()
        if kwargs:
            full_kw.update(kwargs)
        path = '{}:{}'.format(self.hook_cls.module, self.hook_cls.classname)
        cls = import_object(path)
        plugin = cls(*args, **full_kw)
        self._run_plugin(plugin, commits)

    def _run_plugin(self, plugin, commits):
        if plugin.arg_type == "multicommit":
            plugin.on_submit(commits)
            ThreadLocalODMSession.flush_all()
        else:
            for commit in commits:
                plugin.on_submit(commit)
                ThreadLocalODMSession.flush_all()

    def parent_security_context(self):
        return None


# Base Objects
class Plugin(object):
    """base object for post commit plugins"""
    arg_type = None

    def __init__(self, *args, **kwargs):
        pass

    def condition(self, target):
        return True

    def has_ext(self, obj, ext):
        return obj.name.endswith('.' + ext)

    def get_user_for_commit(self, commit):
        user = None
        email = commit.authored['email']
        if email:
            u = User.by_email_address(email)
            if u and c.project.user_in_project(user=u):
                user = u
        return user

    def get_modded_paths(self, commit):
        # find modded file paths
        modded_paths = []
        for path in commit.paths_added.union(commit.diffs.changed):
            if path.endswith('/'):
                repo_dir = commit.get_path(path)
                for child in repo_dir.find_files():
                    if child.path not in modded_paths:
                        modded_paths.append(child.path)
            elif path not in modded_paths:
                modded_paths.append(path)
        return modded_paths


class CommitPlugin(Plugin):
    """base object for post commit plugins that accepts a single commit"""
    arg_type = "commit"

    def on_submit(self, commit):
        pass


class MultiCommitPlugin(Plugin):
    """base object for post commit plugins that accept multiple commits"""
    arg_type = "multicommit"

    def on_submit(self, commits):
        pass


class FinalCommitPlugin(MultiCommitPlugin):
    """pass most recent valid commit only to run"""
    def __init__(self, restrict_branch_to='master'):
        self.restrict_branch_to = restrict_branch_to
        super(MultiCommitPlugin, self).__init__()

    def is_valid_branch(self, commit):
        valid = True
        if commit.repo.type_s == 'Git Repository' and self.restrict_branch_to:
            valid = self.restrict_branch_to in commit.branches()
        return valid

    def on_submit(self, commits):
        #if not self.visualizer.bundle_content:
        for commit in commits[::-1]:
            if self.is_valid_branch(commit):
                self.run(commit)
                break
        else:
            # no commit found on valid branch
            return

    def run(self, commit):
        """Subclasses override this"""
        pass


class PostCommitError(Exception):
    pass


class VisualizerManager(FinalCommitPlugin):
    """This is a bit inefficient, but is the easiest way to sync"""

    def __init__(self, visualizer_shortname, restrict_branch_to='master',
                 **kw):
        self.visualizer = Visualizer.query.get(
            shortname=visualizer_shortname)
        if not self.visualizer:
            self.visualizer = Visualizer(shortname=visualizer_shortname)
        super(VisualizerManager, self).__init__(
            restrict_branch_to=restrict_branch_to)

    def run(self, commit):
        bundle_content = []
        self.visualizer.delete_s3_keys()

        # find the manifest
        for obj in commit.tree.walk(ignore=['.git', '.svn']):
            if obj.name == 'manifest.json':
                manifest_json = json.loads(obj.open().read())
                root_path = os.path.dirname(obj.path)
                break
        else:
            manifest_json = None
            root_path = '/'

        # update from manifest
        if manifest_json:
            self.visualizer.update_from_manifest(manifest_json)

        # upload all files
        root_dir = commit.get_path(root_path)
        for obj in root_dir.walk(ignore=['.git', '.svn']):
            if obj.kind == 'File':
                path = os.path.relpath(obj.path, root_path)
                if self.visualizer.can_upload(path):
                    LOG.info('adding {} to visualizer content'.format(path))
                    bundle_content.append(path)
                    key = self.visualizer.get_s3_key(path)
                    key.set_contents_from_string(obj.open().read())

        self.visualizer.bundle_content = bundle_content
        LOG.info('bundle content {}'.format(self.visualizer.bundle_content))
        session(Visualizer).flush(self.visualizer)
        LOG.info('bundle content {}'.format(self.visualizer.bundle_content))


class ContentPoster(CommitPlugin):
    """Posts new/changed content at paths to specified urls"""

    def __init__(self, urls, paths, method="POST", params=None,
                 restrict_branch_to='master'):
        super(ContentPoster, self).__init__()
        self.urls = urls
        self.path_res = [re.compile(r'^' + p) for p in paths]
        self.method = method
        self.params = params
        self.restrict_branch_to = restrict_branch_to

    def is_valid_branch(self, commit):
        valid = True
        if commit.repo.type_s == 'Git Repository' and self.restrict_branch_to:
            valid = self.restrict_branch_to in commit.branches()
        return valid

    def _write_content(self, obj, dirname):
        # make filename
        fname = obj.name
        if obj.kind == 'Folder':
            fname += '.zip'
        cur = obj
        while os.path.exists(os.path.join(dirname, fname)):
            cur = parent = cur.parent
            fname = parent.name + '_' + fname

        if obj.kind == 'File':
            fp = open(fname, 'w+')
            fp.write(obj.read())
            fp.seek(0)
        else:
            with zipfile.ZipFile(fname, 'w') as zp:
                for f in obj.find_files():
                    arcname = os.path.relpath(obj.path, f.path)
                    zp.writestr(f.read(), arcname)
            fp = open(fname, 'r')
        return fname, fp

    def _iter_matching(self, commit):
        for modded_path in self.get_modded_paths(commit):
            for pattern in self.path_res:
                match = pattern.match(modded_path)
                if match:
                    try:
                        path = match.group('content_path')
                    except IndexError:
                        path = modded_path
                    obj = commit.get_path(path)
                    yield obj

    @contextmanager
    def _open_files(self, commit):
        fps = []
        seen = set()
        with temporary_dir() as dirname:
            try:
                for obj in self._iter_matching(commit):
                    if obj.index_id() not in seen:
                        fp = self._write_content(obj, dirname)
                        fps.append(fp)
                        seen.add(obj.index_id())
                yield fps
            finally:
                for fp in fps:
                    fp[1].close()

    def on_submit(self, commit):
        if not self.is_valid_branch(commit):
            return
        with self._open_files(commit) as files:
            if files:
                submit_func = getattr(requests, self.method.lower())
                for url in self.urls:
                    submit_func(url, files=files, data=self.params)