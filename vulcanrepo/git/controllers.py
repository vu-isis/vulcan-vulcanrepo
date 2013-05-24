import logging

from ming.odm import session
from webob import exc
from pylons import tmpl_context as c, app_globals as g
from tg import expose, redirect
from tg.decorators import without_trailing_slash, with_trailing_slash

from vulcanforge.common.controllers import BaseController
from vulcanforge.common.controllers.decorators import (
    require_post,
    validate_form
)
from vulcanforge.discussion.widgets import ThreadWidget

from vulcanrepo.base.controllers import BaseRepositoryController, TEMPLATE_DIR
from vulcanrepo.base.widgets import SCMLogWidget
from vulcanrepo.git.model import MergeRequest
from .widgets import (
    MergeRequestDisposeWidget,
    MergeRequestFilterWidget,
    MergeRequestWidget
)


LOG = logging.getLogger(__name__)


class GitRootController(BaseRepositoryController):
    # merge_requests = MergeRequestsController()

    @expose(TEMPLATE_DIR + 'no_commits.html')
    @with_trailing_slash
    def index(self, **kw):
        if c.app.repo.heads and c.app.repo.status != 'initializing':
            redirect('folder/{}/'.format(
                c.app.config.options['default_branch_name']))
        return dict()

    @expose(TEMPLATE_DIR + 'tags.html')
    @with_trailing_slash
    def tags(self, **kw):
        return dict(tags=c.app.repo.repo_tags)


class MergeRequestController(BaseController):  # pragma no cover

    def _get_mr_widget(self):
        source_branches = [
            b.name for b in c.app.repo.branches + c.app.repo.tags]
        with c.app.repo.push_upstream_context():
            target_branches = [
                b.name for b in c.app.repo.branches + c.app.repo.tags]
        return MergeRequestWidget(
            source_branches=source_branches,
            target_branches=target_branches)

    @without_trailing_slash
    @expose(TEMPLATE_DIR + 'request_merge.html')
    def request_merge(self, branch=None):
        c.form = self._get_mr_widget()
        if branch is None:
            branch = c.app.repo.branches[0].name
        return dict(source_branch=branch)

    @expose()
    @require_post()
    def do_request_merge(self, **kw):
        kw = self._get_mr_widget().to_python(kw)
        downstream = dict(
            project_id=c.project._id,
            mount_point=c.app.config.options.mount_point,
            commit_id=c.app.repo.commit(kw['source_branch']).object_id)
        with c.app.repo.push_upstream_context():
            mr = MergeRequest.upsert(
                downstream=downstream,
                target_branch=kw['target_branch'],
                summary=kw['summary'],
                description=kw['description'])
            t = ThreadWidget(
                discussion_id=c.app.config.discussion_id,
                artifact_reference=mr.index_id(),
                subject='Discussion for Merge Request #:%s: %s' % (
                    mr.request_number, mr.summary))
            session(t).flush()
            redirect(mr.url())


class MergeRequestsController(BaseController):  # pragma no cover

    class Forms(BaseController.Forms):
        mr_filter = MergeRequestFilterWidget()

    @expose(TEMPLATE_DIR + 'merge_requests.html')
    @validate_form("mr_filter")
    def index(self, status=None):
        status = status or ['open']
        requests = c.app.repo.merge_requests_by_statuses(*status)
        c.mr_filter = self.Forms.mr_filter
        return dict(
            status=status,
            requests=requests)

    @expose()
    def _lookup(self, num, *remainder):
        return MergeRequestController(num), remainder


class MergeRequestController(BaseController):  # pragma no cover

    class Widgets(BaseController.Widgets):
        log_widget = SCMLogWidget()
        thread_widget = ThreadWidget(
            page=None, limit=None, page_size=None, count=None, style='linear')

    class Forms(BaseController.Forms):
        mr_dispose_form = MergeRequestDisposeWidget()

    def __init__(self, num):
        self.req = MergeRequest.query.get(
            request_number=int(num))
        if self.req is None:
            raise exc.HTTPNotFound

    @expose(TEMPLATE_DIR + 'merge_request.html')
    def index(self, page=0, limit=250):
        c.thread = self.Widgets.thread_widget
        c.log_widget = self.Widgets.log_widget
        c.mr_dispose_form = self.Forms.mr_dispose_form
        return dict(
            req=self.req,
            page=page,
            limit=limit,
            count=self.req.discussion_thread.post_count)

    @expose()
    @require_post()
    @validate_form("mr_dispose_form")
    def save(self, status=None):
        g.security.require_access(
            self.req, 'write', message='Write access required')
        self.req.status = status
        redirect('.')
