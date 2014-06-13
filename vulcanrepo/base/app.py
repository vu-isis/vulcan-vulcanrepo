import logging
import os
from json import dumps
from operator import itemgetter
from contextlib import contextmanager

from bson import ObjectId
from paste.deploy.converters import asbool
from webob import exc
from pylons import tmpl_context as c, app_globals as g
from tg import expose, redirect, url, config
from tg.decorators import with_trailing_slash, without_trailing_slash
from vulcanforge.common.app import DefaultAdminController, Application
from vulcanforge.common.controllers.decorators import require_post
from vulcanforge.common.types import SitemapEntry, ConfigOption
from vulcanforge.common.util import push_config
from vulcanforge.common.util.exception import exceptionless
from vulcanforge.resources import Icon

from vulcanrepo.base.model.hook import PostCommitHook
from vulcanrepo.tasks import run_commit_hooks, uninstall as uninstall_task
from .controllers import TEMPLATE_DIR

log = logging.getLogger(__name__)


class RepoIOError(IOError):

    def __init__(self, path, *args, **kwargs):
        super(RepoIOError, self).__init__(*args, **kwargs)
        self.path = path


def format_commit_hook(hook):
    """
    @param hook: vulcanrepo.base.model.hook.PostCommitHook
    @return: dict

    """
    return dict(
        id=str(hook._id),
        shortname=hook.shortname,
        name=hook.name,
        description=hook.description,
        removable=hook.removable
    )


def sanitize_path(path):
    return os.path.normpath(path.replace('\\', '/'))


class Repo_IO(object):

    def __init__(self, commit):
        self.commit = commit
        self._tree_cache = {}

    @contextmanager
    def open(self, path, relative_to=None):
        path = sanitize_path(path)
        if relative_to:
            relative_to = sanitize_path(relative_to)
            if not relative_to in self._tree_cache:
                self._tree_cache[relative_to] = self.commit.tree.get_from_path(
                    relative_to)
            tree = self._tree_cache[relative_to]
        else:
            tree = self.commit.tree
        blob = tree.get_from_path(path)
        if blob:
            yield blob.open()
        else:
            raise RepoIOError(path, 'cannot find {}'.format(path))


class RepositoryApp(Application):
    permissions = dict(Application.permissions,
        write='',
        moderate='Moderate comments',
        unmoderated_post='Add comments without moderation',
        post='Create new topics and add comments'
    )
    config_options = Application.config_options + [
        ConfigOption('cloned_from_project_id', ObjectId, None),
        ConfigOption('cloned_from_repo_id', ObjectId, None),
        ConfigOption('init_from_url', str, None)
    ]
    tool_label = 'Repository'
    default_mount_label = 'Design'
    default_mount_point = 'design'
    ordinal = 2
    forkable = False
    repo = None  # override with a property in child class
    icons = {
        24: 'images/code_24.png',
        32: 'images/code_32.png',
        48: 'images/code_48.png'
    }
    default_hooks = {
        "post_commit": ['visualizer', 'forgeport']
    }
    reference_opts = dict(Application.reference_opts, can_reference=True)
    admin_description = (
        "Your repository is where you store and manage your design project. "
        "Vehicle FORGE advocates the use of version control systems to help "
        "you manage changes in your design over time. You can browse and "
        "administrate improvements to your project, view the current state of "
        "your design artifacts, or download the project to make improvements "
        "of your own."
    )
    admin_actions = {
        "Browse repository": {"url": ""}
    }
    default_acl = {
        'Admin': ['admin'],
        'Developer': ['write', 'moderate'],
        '*authenticated': ['post', 'unmoderated_post'],
        '*anonymous': ['read']
    }
    tasks = {
        'uninstall': uninstall_task
    }

    def __init__(self, project, config):
        Application.__init__(self, project, config)
        self.admin = RepoAdminController(self)

    def main_menu(self):
        """
        Apps should provide their entries to be added to the main nav

        :return: a list of :class:`SitemapEntries <vulcanforge.common.types.SitemapEntry>`

        """
        return [SitemapEntry(self.config.options.mount_label.title(), '.')]

    @property
    @exceptionless([], log)
    def sitemap(self):
        menu_id = self.config.options.mount_label.title()
        with push_config(c, app=self):
            return [
                SitemapEntry(menu_id, '.')[self.sidebar_menu()] ]

    def admin_menu(self):
        admin_url = c.project.url() + 'admin/' + \
                    self.config.options.mount_point + '/'
        links = [
            SitemapEntry(
                'Refresh Repository',
                c.project.url() + self.config.options.mount_point + '/refresh',
                className='nav_child'
            ),
#            SitemapEntry(
#                'Post Commit Hooks',
#                admin_url + 'commit_hooks',
#                className='nav_child'
#            )
        ]
        if self.permissions and g.security.has_access(self, 'admin'):
            links.append(
                SitemapEntry(
                    'Permissions',
                    admin_url + 'permissions',
                    className='nav_child'
                )
            )
        return links

    @exceptionless([], log)
    def sidebar_menu(self):
        if not self.repo or self.repo.status != 'ready':
            return [SitemapEntry(self.repo.status)]
        links = [
            SitemapEntry('Stats',
                         url=self.url + 'stats',
                         ui_icon=Icon('', 'ico-bars'))
        ]
        if self.forkable and self.repo.status == 'ready':
            links.append(
                SitemapEntry(
                    'Fork',
                    c.app.url + 'fork',
                    ui_icon=Icon('', 'ico-fork')
                )
            )

        links.extend(self.get_sidebar_menu_upstream())

        return links

    @exceptionless([], log)
    def get_sidebar_menu_upstream(self):
        cloned_from_repo_id = self.config.options['cloned_from_repo_id']
        cloned_from = self.repo.query.get(_id=cloned_from_repo_id)

        if not cloned_from:
            return []

        links = [
            SitemapEntry('Clone of'),
            SitemapEntry(
                "{} {}".format(
                    cloned_from.project.name,
                    cloned_from.app_config.options['mount_label'],
                ),
                url=cloned_from.url(),
                className='nav_child'
            )
        ]

        return links

    def install(self, project, acl=None):
        self.config.options['project_name'] = project.name
        super(RepositoryApp, self).install(project, acl=acl)

    def uninstall(self, project=None, project_id=None):
        self.tasks['uninstall'].post()

    def _get_default_post_commits(self):
        pchs = []
        for shortname in self.default_hooks.get("post_commit", []):
            plugin = PostCommitHook.query.get(shortname=shortname)
            if plugin:
                pchs.append(dict(plugin_id=plugin._id))
            elif not asbool(config.get('testing_testing')):
                log.warn('Post Commit hook %s not found' % shortname)
        return pchs


class RepoAdminController(DefaultAdminController):

    reindex_on_aclmod = False

    @property
    def repo(self):
        return self.app.repo

    def _check_security(self):
        g.security.require_access(self.app, 'admin')

    @with_trailing_slash
    @expose()
    def index(self, **kw):
        redirect('extensions')

    @without_trailing_slash
    @expose(TEMPLATE_DIR + 'admin_extensions.html')
    def extensions(self, **kw):
        return dict(
            app=self.app,
            allow_config=True,
            additional_viewable_extensions=getattr(
                self.repo, 'additional_viewable_extensions', '')
        )

    @without_trailing_slash
    @expose()
    @require_post()
    def set_extensions(self, **post_data):
        self.repo.additional_viewable_extensions = \
            post_data['additional_viewable_extensions']

    @expose(TEMPLATE_DIR + 'commit_hooks.html')
    def commit_hooks(self):
        hooks = self.active_hooks()['hooks']
        admin_url = c.project.url() + 'admin/' + \
                    self.app.config.options.mount_point + '/'
        return dict(
            app=self.app,
            hooks_json=dumps(hooks),
            admin_url=admin_url,
            allow_config=g.security.has_access(self.app, 'admin')
        )

    @expose('json')
    def active_hooks(self):
        return dict(
            hooks=[format_commit_hook(h)
                   for h, a, k in self.repo.get_hooks()
                   if g.security.has_access(h, 'read')]
        )

    @expose('json')
    def browsable_hooks(self):
        cur_hooks = map(itemgetter('plugin_id'), self.repo.post_commit_hooks)
        cur = PostCommitHook.query.find({
            '_id': {'$nin': cur_hooks}
        })
        hooks = [format_commit_hook(h)
                 for h in cur if g.security.has_access(h, 'install')]
        return dict(hooks=hooks)

    @expose('json')
    @require_post()
    def add_commit_hook(self, hook_id, **kw):
        hook_id = ObjectId(hook_id)
        hook = PostCommitHook.query.get(_id=hook_id)
        if hook is None:
            raise exc.HTTPNotFound('Post Commit Hook')
        g.security.require_access(hook, 'install')
        self.repo.upsert_post_commit_hook(hook)
        return format_commit_hook(hook)

    @expose()
    @require_post()
    def set_hook_order(self, hook_ids, **kw):
        new_hooks = []
        old_hooks = self.repo.post_commit_hooks[:]
        for hook_id in map(ObjectId, hook_ids.split(',')):
            for i, pch in enumerate(old_hooks):
                if pch.plugin_id == hook_id:
                    new_hooks.append(pch)
                    del old_hooks[i]
                    break
            else:
                log.warn('Hook %s not found in %s', hook_id,
                         self.app.config.options['mount_label'])
        self.repo.post_commit_hooks = new_hooks

    @expose('json')
    @require_post()
    def remove_commit_hook(self, hook_id, **kw):
        success = False
        hook_id = ObjectId(hook_id)
        hook = PostCommitHook.query.get(_id=hook_id)
        if hook is not None and hook.removable:
            success = self.repo.remove_post_commit_hook(hook_id)
        return dict(success=success)

    @expose('json')
    @require_post()
    def run_hooks(self, commits=None, **kw):
        with push_config(c, app=self.app):
            run_commit_hooks.post(commits=commits)
        commits_msg = 'All Commits' if commits == 'all' else 'Last Commit'
        msg = 'Running Post Commit Hooks for ' + commits_msg
        return dict(success=True, msg=msg)
