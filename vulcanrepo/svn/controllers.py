from tg import expose, redirect
from tg.decorators import with_trailing_slash
from pylons import tmpl_context as c, app_globals as g
from vulcanforge.common.controllers.decorators import require_post

from vulcanrepo.base.controllers import (
    BaseRepositoryController,
    RootRestController,
    TEMPLATE_DIR)
from vulcanrepo.svn.model.svn import FileExists
from .widgets.svn import SVNCommitAuthor


class SVNRootController(BaseRepositoryController):

    class Widgets(BaseRepositoryController.Widgets):
        commit_author_widget = SVNCommitAuthor()

    @expose(TEMPLATE_DIR + 'no_commits.html')
    @with_trailing_slash
    def index(self, **kw):
        if c.app.repo.head and c.app.repo.status != 'initializing':
            redirect('folder/head/')
        return dict()

    @expose('jinja:vulcanrepo.svn:templates/file.html')
    def file(self, *args, **kw):
        return super(SVNRootController, self).file(*args, **kw)


class SVNRestController(RootRestController, SVNRootController):

    @require_post()
    @expose('json')
    def add_folder(self, folder_path, msg=None, clone_scheme=None, **kwargs):
        g.security.require_access(c.app, 'write')
        if not folder_path.startswith('/'):
            folder_path = '/' + folder_path
        if msg is None:
            msg = 'Added empty folder {}'.format(folder_path)
        try:
            c.app.repo.add_folder(folder_path, msg=msg, author=c.user.username)
        except FileExists:
            return {
                "success": False,
                "status": "Folder exists"
            }
        result = {
            "success": True,
            "status": "OK"
        }
        if clone_scheme and clone_scheme in ('http', 'https', 'ssh'):
            result["svnUrl"] = c.app.repo.clone_url(clone_scheme)
        return result
