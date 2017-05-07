#-*- python -*-
from bson import ObjectId
import datetime
import logging

# Non-stdlib imports
from pylons import tmpl_context as c

from ming.utils import LazyProperty
from ming.odm.odmsession import ThreadLocalODMSession
from vulcanforge.common.tool import ConfigOption, SitemapEntry
from vulcanforge.common.util import push_config
from vulcanforge.common.util.counts import get_info
from vulcanforge.common.util.exception import exceptionless
from vulcanforge.project.model import Project
from vulcanforge.resources import Icon

from vulcanrepo.base.app import RepositoryApp
from vulcanrepo.base.controllers import RootRestController
from vulcanrepo import tasks as repo_tasks
from . import model as GM
from . import version
from .controllers import GitRootController

LOG = logging.getLogger(__name__)


class ForgeGitApp(RepositoryApp):
    """This is the Git app for PyForge"""
    __version__ = version.__version__
    tool_label = 'Git'
    static_folder = 'Git'
    ordinal = 2
    forkable = True
    config_options = RepositoryApp.config_options + [
        ConfigOption('default_branch_name', str, 'master')
    ]

    def __init__(self, project, config):
        super(ForgeGitApp, self).__init__(project, config)
        self.root = GitRootController()
        self.api_root = RootRestController()

    @LazyProperty
    def repo(self):
        return GM.GitRepository.query.get(app_config_id=self.config._id)

    def install(self, project, acl=None):
        """Create repo object for this tool"""
        super(ForgeGitApp, self).install(project, acl=acl)
        GM.GitRepository(
            name=self.config.options.mount_point + '.git',
            tool='git',
            status='initializing',
            post_commit_hooks=self._get_default_post_commits()
        )
        ThreadLocalODMSession.flush_all()
        cloned_from_project_id = self.config.options.get(
            'cloned_from_project_id')
        cloned_from_repo_id = self.config.options.get('cloned_from_repo_id')
        init_from_url = self.config.options.get('init_from_url')
        if cloned_from_project_id:
            from_project = Project.query_get(_id=cloned_from_project_id)
            with push_config(c, project=from_project):
                cloned_from = GM.GitRepository.query.get(
                    _id=cloned_from_repo_id)
                repo_tasks.clone.post(
                    cloned_from_name=cloned_from.app.config.script_name(),
                    cloned_from_url=cloned_from.full_fs_path)
        elif init_from_url:
            repo_tasks.clone.post(
                cloned_from_name=None, cloned_from_url=init_from_url)
        else:
            repo_tasks.init.post()

    def uninstall(self, *args, **kw):
        GM.MergeRequest.query.remove(dict(app_config_id=c.app.config._id))
        GM.GitCommit.query.remove(dict(app_config_id=c.app.config._id))
        super(ForgeGitApp, self).uninstall(*args, **kw)

    def sidebar_menu(self):
        menu = [
            SitemapEntry(
                'Commits',
                '{}history/{}'.format(
                    c.app.url, self.config.options.default_branch_name),
                ui_icon=Icon('','ico-folder_fill'))
        ]
        menu.extend(super(ForgeGitApp, self).sidebar_menu())

        ## merge requests are commented out until they can be fixed
        # menu.extend(self.get_sidebar_menu_merges())

        menu.extend(self.get_sidebar_menu_branches())
        menu.extend(self.get_sidebar_menu_tags())

        return menu

    @exceptionless([], LOG)
    def get_sidebar_menu_branches(self):
        links = []
        if self.repo.branches:
            links.append(SitemapEntry('Branches'))
            links.extend(
                self._rev_sitemap_entries(
                    self.repo.branches, className='nav_child repo-branch'))
        return links

    @exceptionless([], LOG)
    def get_sidebar_menu_tags(self):
        links = []
        if self.repo.repo_tags:
            links.append(SitemapEntry('Tags'))
            links.extend(
                self._rev_sitemap_entries(
                    self.repo.repo_tags,
                    className='nav_child repo-tag',
                    max_revs=10,
                    more_url='{}tags/?branch={}'.format(
                        self.url, self.config.options.default_branch_name)
                )
            )
        return links

    def _rev_sitemap_entries(self, revs, className='nav_child', max_revs=None,
                             more_url=None):
        links = []
        for i, b in enumerate(revs):
            links.append(SitemapEntry(
                b.name,
                self.url + 'folder/' + b.name + '/',
                className=className))
            if max_revs and i == max_revs:
                if more_url:
                    links.append(SitemapEntry(
                        'More...',
                        more_url,
                        className='nav_child',
                        small=len(revs) - max_revs
                    ))
                break
        return links

    def get_sidebar_menu_merges(self):
        links = []
        if len(self.repo.branches):
            links.append(SitemapEntry(
                'Request Merge',
                c.app.url + 'request_merge',
                ui_icon=Icon('', 'ico-curved_arrow'),
                className='nav_child'))
        pending_upstream_merges = self.repo.pending_upstream_merges()
        if pending_upstream_merges:
            links.append(SitemapEntry(
                'Pending Merges',
                self.repo.upstream_repo.url +
                'merge_requests/',
                className='nav_child',
                small=pending_upstream_merges))
            merge_requests = self.repo.merge_requests_by_statuses('open')
            merge_request_count = merge_requests.count()
            if merge_request_count:
                links.append(SitemapEntry(
                    'Merge Requests',
                    c.app.url + 'merge_requests/',
                    className='nav_child',
                    small=merge_request_count))

    def artifact_counts(self, since=None):
        db, commit_coll = GM.GitCommit.get_pymongo_db_and_collection()

        new_commit_count = commit_count = commit_coll.find({
            "app_config_id":self.config._id
        }).count()
        if since is not None and isinstance(since, datetime.datetime) :
            new_commit_count = commit_coll.find({
                "app_config_id":self.config._id,
                "_id":{"$gt":ObjectId.from_datetime(since)}
            }).count()

        return dict(
            new=new_commit_count,
            all=commit_count
        )

    @classmethod
    def artifact_counts_by_kind(cls, app_configs, app_visits, tool_name,
                                trefs=[]):
        db, coll = GM.GitCommit.get_pymongo_db_and_collection()
        size_item = None
        return get_info(coll, app_configs, app_visits, tool_name, size_item,
                        has_deleted=False, trefs=trefs)
