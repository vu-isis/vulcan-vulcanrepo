import logging

from ming.odm.odmsession import ThreadLocalODMSession
from vulcanforge.migration.base import BaseMigration
from vulcanforge.project.model import AppConfig

LOG = logging.getLogger(__name__)


class UnifyAppPermissions(BaseMigration):
    """WARNING: this migration is NOT idempotent. DO NOT RUN TWICE"""

    def run(self):

        # Change old permission names to new ones
        for app_config in AppConfig.query.find().all():
            # repository permission: delete 'create' and 'configure' permissions
            if app_config.tool_name in ('svn', 'git'):
                new_acl = []
                for ace in app_config.acl:
                    if ace.permission not in ('configure', 'create'):
                        new_acl.append(ace)

                app_config.acl = new_acl

        ThreadLocalODMSession.flush_all()
