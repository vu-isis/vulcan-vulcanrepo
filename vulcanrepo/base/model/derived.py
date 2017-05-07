from datetime import datetime
import logging
import re
import json
import urllib

import ming.schema
from ming.odm import (
    FieldProperty,
    ForeignIdProperty,
    session
)
from ming.utils import LazyProperty
from pylons import tmpl_context as c, app_globals as g
from vulcanforge.artifact.model import Artifact, ArtifactReference, Shortlink
from vulcanforge.auth.model import User
from vulcanforge.common.model.base import BaseMappedClass
from vulcanrepo.base.model import RepoVersionSpec, RepoContentRelation
from vulcanforge.common.exceptions import NoSuchAppError
from vulcanforge.common.model.session import (
    main_orm_session,
    repository_orm_session
)
from vulcanforge.common.util import push_config
from vulcanforge.common.util.json_util import strict_load
from vulcanforge.neighborhood.model import Neighborhood
from vulcanforge.project.model import AppConfig, Project

LOG = logging.getLogger(__name__)
BLOB_URL_RE = re.compile(r'''
    /[a-z_0-9]+/(?P<shortname>[A-z][-A-z0-9]+)/ # nbhd/project shortname
    (?P<mount_point>[a-z][-a-z0-9]{2,})/     # app mount point
    file/(?P<commit>[a-z0-9]+)  # commit id
    (?P<path>/[^\?]*)           # path to file
    (?:\?.*)?$                      # dont care about query params
    ''', re.VERBOSE)


class RepoDerivedObject(BaseMappedClass):
    """Abstract class for objects that point to a repository file. Enables
    parsing and persistence of information based on files committed to the
    repository. Typically managed by a post commit hook.

    """

    class __mongometa__:
        name = 'generic-file-pointer'
        session = main_orm_session
        indexes = [
            'project_id',
            'app_config_id',
            'object_id',
            'neighborhood_id',
            ('project_id', 'app_config_id'),
            ('blob_spec.app_config_id', 'blob_spec.path',
             'blob_spec.version_id')
        ]

    _id = FieldProperty(ming.schema.ObjectId)
    project_id = ForeignIdProperty(
        Project,
        if_missing=lambda: c.project._id if hasattr(c, 'project') else None
    )
    neighborhood_id = ForeignIdProperty(
        Neighborhood,
        if_missing=lambda: c.project.neighborhood_id
            if hasattr(c, 'project') else None
    )
    app_config_id = ForeignIdProperty(
        AppConfig,
        if_missing=lambda: c.app.config._id if hasattr(c, 'app') else None
    )
    blob_spec = RepoVersionSpec()
    blob = RepoContentRelation(via="blob_spec")
    version = FieldProperty(int, if_missing=1)
    author_ids = FieldProperty([ming.schema.ObjectId], if_missing=[])
    mod_date = FieldProperty(datetime, if_missing=datetime.utcnow)

    def __json__(self):
        return {
            'id': self._id,
            'title': self.blob_spec.path,
            'display_name': self.display_name,
            'file_url': self.get_blob_url(),
            'file_path': self.blob_spec.path,
            'version': self.version
        }

    @classmethod
    def get_from_blob(cls, blob, **kw):
        """
        Gets a object, given a repo file.

        Note that this cannot use the commit object_id, because each
        derived object can represent a file across multiple commits

        """
        query = {
            'blob_spec.app_config_id': blob.repo.app_config_id,
            'blob_spec.version_id': blob.version_id,
            'blob_spec.path': blob.path
        }
        query.update(kw)
        return cls.query.find(query).first()

    @classmethod
    def get_accessible(cls, query=None, project=None, permission='read',
                       user=None):
        """Query accessible objects"""
        if project is None:
            project = c.project
        if user is None:
            user = c.user
        if query is None:
            query = {}
        if permission == 'read':
            ac_ids = [ac._id for ac in project.app_configs
                      if ac.is_visible_to(user)]
        else:
            ac_ids = [ac._id for ac in project.app_configs
                      if ac.has_access(permission)]
        query.update({
            'project_id': project._id,
            'app_config_id': {'$in': ac_ids}
        })
        return cls.query.find(query)

    @classmethod
    def get_from_blob_url(cls, url):
        """Query for an object based on repository file url"""
        match = BLOB_URL_RE.match(url)
        if not match:
            return None

        project = Project.by_shortname(match.group('shortname'))
        if not project:
            return None

        app = project.app_instance(match.group('mount_point'))
        if app and app.repo:
            with push_config(c, project=project, app=app):
                ci = app.repo.commit(match.group('commit'))
                if not ci:
                    return None
                blob = ci.get_path(match.group('path'))
                if blob:
                    return cls.get_from_blob(blob)

    @classmethod
    def from_blob(cls, blob, process=True, **kw):
        """Upserts a derived object, given a blob"""
        old = cls.query.find({
            'blob_spec.app_config_id': blob.repo.app_config_id,
            'blob_spec.path': blob.path
        }).first()

        if old and old.blob_spec.version_id == blob.version_id:
            # already current
            LOG.debug('Found existing blob for %s: %s', blob.url(),
                      old.blob_spec)
            return old

        if old:
            new = old.increment_from_blob(blob, **kw)
        else:
            new = cls(**kw)
        new.blob = blob
        author = blob.commit.user
        if author and author._id not in new.author_ids:
            new.author_ids.append(author._id)
        session(cls).flush(new)

        LOG.debug('postprocess %s? %s', blob.url(), process)
        if process:
            new.post_process()

        return new

    @LazyProperty
    def neighborhood(self):
        return Neighborhood.query.get(_id=self.neighborhood_id)

    @property
    def app_config(self):
        return AppConfig.query.get(_id=self.app_config_id)

    @property
    def project(self):
        return Project.query_get(_id=self.project_id)

    @property
    def authors(self):
        """Returns User objects of commit authors, if found"""
        return User.query.find({'_id': {"$in": self.author_ids}})

    @LazyProperty
    def repo(self):
        """Get the repository instance"""
        try:
            with g.context_manager.push(app_config_id=self.app_config_id):
                return c.app.repo
        except NoSuchAppError:
            return None

    @property
    def display_name(self):
        return self.path

    @property
    def path(self):
        return self.blob_spec.path

    def shorthand_id(self):
        """For markdown embeds and displaying artifact links"""
        return '{path}_{_id}'.format(path=self.path, _id=self._id)

    def get_blob_url(self):
        """Get url for underlying repository file. Faster than calling
        self.blob.url() because it makes no calls to the underlying repository

        """
        if self.app_config:
            return self.app_config.url() + \
                   'file/' + \
                   self.blob_spec.rev.split(':')[-1] + \
                   self.blob_spec.path

    def get_blob_at_rev(self, rev):
        """Get the underlying file at a specified revision, providing the file
        has not changed paths.

        rev should be a string or int identifying the revision, as appropriate
        for the Repository.commit method.

        """
        if self.repo:
            ci = self.repo.commit(rev)
            if ci:
                return ci.get_path(self.blob_spec.path)

    def increment_from_blob(self, blob, **kw):
        """Increment the version and point to the new file"""
        kw.setdefault('mod_date', self.blob.commit.committed.date)
        for k, v in kw.items():
            setattr(self, k, v)
        self.version += 1
        self.blob = blob
        return self

    def render(self, shortname=None, **kw):
        """Find a visualizer associated with the underlying file and invoke it
        on the file.

        """
        content = None
        with g.context_manager.push(app_config_id=self.app_config_id):
            if self.blob:
                content = g.visualize_url(self.blob.raw_url()).render(**kw)
        if not content:
            content = "Could not visualize {}".format(self.blob_spec.path)
        return content

    def post_process(self):
        """Hook for post processing. Called from `from_blob` method."""
        pass

    def users(self):
        """retrieves all current members of the associated project"""
        uids = set()
        users = []
        for u in self.project.users():
            if not u._id in uids:
                uids.add(u._id)
                users.append(u)
        return users

    def get_json_content(self, strict=False):
        """Load repository file content as json"""
        loader = strict_load if strict else json.load
        return loader(self.blob.open())


class RepoAbstraction(Artifact):
    """Artifacts abstracted from a repository object.

    These differ from RepoDerivedObject in that they are artifacts. They were
    also created for the case in which there are many of these for an
    individual repository file, while RepoDerivedObject was created for one
    to one.

    """

    class __mongometa__:
        name = "repo-abstraction"
        session = repository_orm_session

    type_s = "Repository Abstraction"
    name = FieldProperty(str)
    ref_id = ForeignIdProperty(ArtifactReference, if_missing='')
    relative_id = FieldProperty(str)
    query_params = FieldProperty({str: str})

    @classmethod
    def upsert(cls, ref_id, relative_id, add_reference=True, **kwargs):
        isnew = False
        artifact = cls.query.get(ref_id=ref_id, relative_id=relative_id)
        if artifact is None:
            isnew = True
            artifact = cls(ref_id=ref_id, relative_id=relative_id)
        for key, val in kwargs.iteritems():
            setattr(artifact, key, val)
        if isnew and add_reference:
            session(artifact).flush(artifact)
            artifact.ref = ArtifactReference.from_artifact(artifact)
            Shortlink.from_artifact(artifact)
        return artifact, isnew

    @property
    def related_instance(self):
        return None

    def index(self, text_objects=[], **kwargs):
        return None

    def link_text(self):
        return self.name

    def ref_category(self):
        return u"Abstraction"

    def url(self):
        if self.related_instance:
            url = self.related_instance.url()
            if self.query_params:
                query_str = urllib.urlencode(self.query_params)
                if '?' not in url:
                    query_str = '?' + query_str
                url += query_str
            return url

    def shorthand_id(self):
        if self.related_instance:
            return '{' + self.relative_id + '}' + \
                   self.related_instance.shorthand_id()
