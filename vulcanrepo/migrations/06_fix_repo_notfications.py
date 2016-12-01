import re

from ming.odm import ThreadLocalODMSession
from vulcanforge.migration.base import BaseMigration
from vulcanforge.notification.model import Notification
from vulcanrepo.svn.model import SVNRepository, SVNCommit
from vulcanrepo.git.model import GitCommit

COMMIT_REGEX = re.compile("^.*?/([a-f0-9]+)/?>$", re.M)
COMMIT_REGEX_2 = re.compile('^.*?/([a-f0-9]+)".*$', re.M)


class FixRepoNotifications(BaseMigration):
    def run(self):

        # fix git notifications
        nc = Notification.query.find(dict(author_id=None, tool_name="git"))
        total = nc.count()
        count = 0
        for n in nc:
            mo = COMMIT_REGEX.match(n.text)
            if not mo:
                mo = COMMIT_REGEX_2.match(n.text)
            if mo:
                gc = GitCommit.query.get(object_id=mo.group(1))
                if gc and gc.user:
                    count += 1
                    n.author_id = gc.user._id
        msg = 'Updated {} of {} Git repository notifications.'
        self.write_output(msg.format(count, total))

        # fix svn notifications
        nc = Notification.query.find(dict(author_id=None, tool_name="svn"))
        total = nc.count()
        count = 0
        for n in nc:
            mo = COMMIT_REGEX.match(n.text)
            if not mo:
                mo = COMMIT_REGEX_2.match(n.text)
            if mo:
                r = SVNRepository.query.get(app_config_id=n.app_config_id)
                if r:
                    sc = r.commit(mo.group(1))
                    if sc and sc.user:
                        count += 1
                        n.author_id = sc.user._id
        msg = 'Updated {} of {} Svn repository notifications.'
        self.write_output(msg.format(count, total))
        ThreadLocalODMSession.flush_all()
