#-*- python -*-
from bson import ObjectId
import datetime
import logging

# Non-stdlib imports
from pylons import tmpl_context as c
from ming.utils import LazyProperty
from ming.odm.odmsession import ThreadLocalODMSession
from vulcanforge.common.tool import SitemapEntry
from vulcanforge.common.util import push_config
from vulcanforge.common.util.counts import get_info
from vulcanforge.project.model import Project
from vulcanforge.resources import Icon

from vulcanrepo import tasks as repo_tasks
from vulcanrepo.base.app import RepositoryApp

# Local imports
from . import model as SM
from . import version
from .controllers import SVNRootController, SVNRestController

LOG = logging.getLogger(__name__)


class ForgeSVNApp(RepositoryApp):
    """This is the SVN app for PyForge"""
    __version__ = version.__version__
    tool_label = 'SVN'
    static_folder = 'SVN'
    ordinal = 4
    forkable = True

    def __init__(self, project, config):
        super(ForgeSVNApp, self).__init__(project, config)
        self.root = SVNRootController()
        self.api_root = SVNRestController()

    @LazyProperty
    def repo(self):
        return SM.SVNRepository.query.get(app_config_id=self.config._id)

    def sidebar_menu(self):
        menu = [
            SitemapEntry(
                'Commits',
                '{}history/head'.format(c.app.url),
                ui_icon=Icon('', 'ico-folder_fill'))
        ]
        menu.extend(super(ForgeSVNApp, self).sidebar_menu())
        return menu

    def install(self, project, acl=None):
        """Create repo object for this tool"""
        super(ForgeSVNApp, self).install(project, acl=acl)
        SM.SVNRepository(
            name=self.config.options.mount_point,
            tool='svn',
            status='initializing',
            post_commit_hooks=self._get_default_post_commits()
        )
        ThreadLocalODMSession.flush_all()  # to ensure task finds the repo
        cloned_from_project_id = self.config.options.get(
            'cloned_from_project_id')
        cloned_from_repo_id = self.config.options.get('cloned_from_repo_id')
        init_from_url = self.config.options.get('init_from_url')
        if cloned_from_repo_id is not None:
            with push_config(c,
                    project=Project.query.get(_id=cloned_from_project_id)):
                cloned_from = SM.SVNRepository.query.get(
                    _id=cloned_from_repo_id)
                repo_tasks.clone.post(
                    cloned_from_name=cloned_from.app.config.script_name(),
                    cloned_from_url=cloned_from.full_fs_path)
        elif init_from_url:
            repo_tasks.clone.post(
                cloned_from_name=None,
                cloned_from_url=init_from_url)
        else:
            repo_tasks.init.post()

    def uninstall(self, *args, **kw):
        SM.SVNCommit.query.remove(dict(app_config_id=c.app.config._id))
        super(ForgeSVNApp, self).uninstall(*args, **kw)

    def artifact_counts(self, since=None):
        db, commit_coll = SM.SVNCommit.get_pymongo_db_and_collection()

        new_commit_count = commit_count = commit_coll.find({
            "app_config_id": self.config._id
        }).count()
        if since is not None and isinstance(since, datetime.datetime):
            new_commit_count = commit_coll.find({
                "app_config_id": self.config._id,
                "_id": {"$gt": ObjectId.from_datetime(since)}
            }).count()

        return dict(
            new=new_commit_count,
            all=commit_count
        )

    @classmethod
    def artifact_counts_by_kind(cls, app_configs, app_visits, tool_name,
                                trefs=None):
        db, coll = SM.SVNCommit.get_pymongo_db_and_collection()
        size_item = None
        return get_info(coll, app_configs, app_visits, tool_name, size_item,
                        has_deleted=False, trefs=trefs)
