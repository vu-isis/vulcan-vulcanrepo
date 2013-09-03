import logging
import bson
import os
import json

from ming import schema as S
from ming.odm import FieldProperty, ThreadLocalODMSession, session
from ming.odm.declarative import MappedClass
from pylons import tmpl_context as c
from vulcanforge.auth.schema import ACL
from vulcanforge.auth.model import User
from vulcanforge.common.model.session import repository_orm_session
from vulcanforge.common.util.filesystem import import_object
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
    def from_object(cls, obj, **kwargs):
        return cls(
            hook_cls={
                "module": obj.__module__,
                "classname": obj.__class__.__name__
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


class PostCommitError(Exception):
    pass


class VisualizerManager(MultiCommitPlugin):
    """This is a bit inefficient, but is the easiest way to sync"""

    def __init__(self, visualizer_shortname, restrict_branch_to='master',
                 **kw):
        self.visualizer = Visualizer.query.get(
            shortname=visualizer_shortname)
        if not self.visualizer:
            self.visualizer = Visualizer(shortname=visualizer_shortname)
        self.restrict_branch_to = restrict_branch_to
        super(VisualizerManager, self).__init__()

    def is_valid_branch(self, commit):
        valid = True
        if commit.repo.type_s == 'Git Repository' and self.restrict_branch_to:
            valid = self.restrict_branch_to in commit.branches()
        return valid

    def init_from_commit(self, commit):
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

    def on_submit(self, commits):
        #if not self.visualizer.bundle_content:
        for commit in commits[::-1]:
            if self.is_valid_branch(commit):
                self.init_from_commit(commit)
                break
        else:
            # no commit found on valid branch
            return