from tg import expose, redirect
from tg.decorators import with_trailing_slash
from pylons import tmpl_context as c

from vulcanrepo.base.controllers import (
    BaseRepositoryController,
    RootRestController,
    TEMPLATE_DIR)
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
    pass
