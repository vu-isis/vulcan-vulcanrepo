import logging
import os
import json

from ming import schema as S
from ming.odm import FieldProperty, ThreadLocalODMSession
from ming.odm.declarative import MappedClass
from pylons import tmpl_context as c, app_globals as g
from vulcanforge.auth.schema import ACL, ACE, EVERYONE
from vulcanforge.auth.model import User
from vulcanforge.common.model.session import repository_orm_session
from vulcanforge.common.util.filesystem import import_object
from vulcanforge.visualize.model import VisualizerConfig
from vulcanforge.visualize.s3hosted import S3HostedVisualizer

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
        cls_query = {
            "hook_cls.module": obj.__module__,
            "hook_cls.classname": obj.__name__
        }
        kwargs.update(cls_query)
        pch = cls.query.get(**kwargs)
        if not pch:
            pch = cls.from_object(obj, **kwargs)
            isnew = True
        return pch, isnew

    @classmethod
    def from_object(cls, obj, acl=None, description=None, **kwargs):
        if description is None:
            description = getattr(obj, "description", '')
        if acl is None:
            acl = getattr(obj, "acl", [
                ACE.allow(EVERYONE, 'read'),
                ACE.allow(EVERYONE, 'install')
            ])
        inst = cls(
            hook_cls={
                "module": obj.__module__,
                "classname": obj.__name__
            },
            description=description,
            acl=acl,
            **kwargs)
        inst.description = getattr(obj, "description", '')
        return inst

    @property
    def hook(self):
        """return hook class (uninstantiated)"""
        path = '{}:{}'.format(self.hook_cls.module, self.hook_cls.classname)
        cls = import_object(path)
        return cls

    def delete(self):
        purge_hook.post(self._id)
        super(PostCommitHook, self).delete()

    def run(self, commits, args=(), kwargs=None):
        if not args:
            args = self.default_args
        full_kw = self.default_kwargs.copy()
        if kwargs:
            full_kw.update(kwargs)
        plugin = self.hook(*args, **full_kw)
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


class VisualizerHook(CommitPlugin):
    """Calls on_upload hook for visualizers"""
    def on_submit(self, commit):
        for obj in commit.files_added + commit.files_modified:
            obj.trigger_vis_upload_hook()
        for obj in commit.files_removed:
            for pfile in obj.find_processed_files():
                pfile.delete()


class VisualizerManager(MultiCommitPlugin):
    """Syncs repo content with a S3HostedVisualizer"""

    def __init__(self, visualizer_shortname, restrict_branch_to='master'):
        vis_config = VisualizerConfig.query.get(shortname=visualizer_shortname)
        if not vis_config:
            vis_config = VisualizerConfig.from_visualizer(
                S3HostedVisualizer, shortname=visualizer_shortname)
        self.visualizer = vis_config.load()
        self.restrict_branch_to = restrict_branch_to
        super(VisualizerManager, self).__init__()

    def is_valid_branch(self, commit):
        valid = True
        if commit.repo.type_s == 'Git Repository' and self.restrict_branch_to:
            valid = self.restrict_branch_to in commit.branches()
        return valid

    def init_from_commit(self, commit):
        # find the manifest
        for obj in commit.tree.walk(ignore=['.git', '.svn']):
            if obj.name == 'manifest.json':
                manifest_json = json.loads(obj.open().read())
                root_path = os.path.dirname(obj.path)
                LOG.info('manifest.json found at %s', obj.path)
                break
        else:
            manifest_json = None
            root_path = '/'
            LOG.info('No manifest.json found in repo %s', commit.repo.url())

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
                    self.visualizer.upload_file(path, obj)

        g.visualizer_mapper.invalidate_cache()

    def on_submit(self, commits):
        # loop through the commits backwards until one is found on a valid
        # branch, if any
        for commit in commits[::-1]:
            if self.is_valid_branch(commit):
                self.init_from_commit(commit)
                break
        else:
            # no commit found on valid branch
            return