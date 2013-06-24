from cPickle import dumps, loads
import bson

from ming import schema as S
from ming.odm import FieldProperty, ThreadLocalODMSession
from ming.odm.declarative import MappedClass
from vulcanforge.auth.schema import ACL
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
