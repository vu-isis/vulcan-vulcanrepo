from cPickle import dumps, loads
import bson

from ming import schema as S
from ming.odm import FieldProperty, ThreadLocalODMSession
from ming.odm.declarative import MappedClass
from pylons import tmpl_context as c
from vulcanforge.auth.schema import ACL
from vulcanforge.auth.model import User
from vulcanforge.common.model.session import repository_orm_session

from vulcanrepo.tasks import purge_hook


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
    cls = FieldProperty(S.Binary)
    default_args = FieldProperty([None])
    default_kwargs = FieldProperty({str: None})
    acl = FieldProperty(ACL(permissions=['install', 'read']))

    @classmethod
    def from_object(cls, object, **kwargs):
        return cls(cls=bson.Binary(dumps(object)), **kwargs)

    def delete(self):
        purge_hook.post(self._id)
        super(PostCommitHook, self).delete()

    def run(self, commits, args=(), kwargs=None):
        if not args:
            args = self.default_args
        full_kw = self.default_kwargs.copy()
        if kwargs:
            full_kw.update(kwargs)
        cls = loads(str(self.cls))
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
