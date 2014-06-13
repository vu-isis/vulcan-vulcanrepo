import os
import logging

from pylons import response, app_globals as g, tmpl_context as c, request
from tg import expose
from webob import exc
from vulcanforge.auth.model import User
from vulcanforge.common.controllers.rest import (
    RestController,
    WebServiceAuthController
)
from vulcanforge.neighborhood.model import Neighborhood
from vulcanforge.project.exceptions import NoSuchProjectError

from vulcanrepo.forgeport.controllers import ForgePortRestController

LOG = logging.getLogger(__name__)


class RepoRestController(RestController):
    forge_port = ForgePortRestController()


class RepoWebServiceAuthController(WebServiceAuthController):

    @expose('json')
    def repo_permissions(self, repo_path=None, username=None, **kw):
        """Expects repo_path to be a filesystem path like
            <tool_type>/<project>.<neighborhood>/<mount_point>[.git]
        unless the <neighborhood> is 'p', in which case it is
            <tool_type>/<project>/<mount_point>[.git]

        Returns JSON describing this user's permissions on that repo.
        """
        disallow = dict(
            allow_read=False,
            allow_write=False,
            allow_create=False
        )
        if not repo_path:
            response.status = 400
            return dict(disallow, error='no path specified')
            # Find the user
        user = User.by_username(username)
        if not user:
            response.status = 404
            return dict(disallow, error='unknown user')
        if user.disabled:
            response.status = 404
            return dict(disallow, error='user is disabled')

        parsed = filter(None, repo_path.split('/'))
        project = os.path.splitext(parsed[1])[0]
        mount = os.path.splitext(parsed[2])[0]
        try:
            g.context_manager.set(project, mount)
        except NoSuchProjectError:
            n = Neighborhood.by_prefix(project)
            if n:
                g.context_manager.set('--init--', mount, neighborhood=n)
            else:
                LOG.info("Can't find project from repo_path %s", repo_path)
                response.status = 404
                return dict(disallow, error='unknown project')

        if c.app is None:
            LOG.info("Can't find repo at %s on repo_path %s", mount, repo_path)
            return disallow
        return {
            'allow_read': g.security.has_access(c.app, 'read', user=user),
            'allow_write': g.security.has_access(c.app, 'write', user=user),
            'allow_create': g.security.has_access(c.app, 'write', user=user)
        }

    @expose()
    def authenticate_user(self, username, password):
        try:
            g.auth_provider.login()
        except exc.HTTPUnauthorized:
            request.environ['pylons.status_code_redirect'] = False
            raise exc.HTTPForbidden()
        return ''

    @expose('json')
    def get_pub_key(self, username):
        pub_key = None
        user = User.by_username(username)
        if user and not user.disabled:
            pub_key = user.public_key or None
        return {'public_key': pub_key}

    @expose('json')
    def os_id_map(self):
        os_ids = {}
        for user in User.query.find({"disabled": False}):
            if user.is_real_user():
                os_ids[user.username] = user.os_id
        return os_ids