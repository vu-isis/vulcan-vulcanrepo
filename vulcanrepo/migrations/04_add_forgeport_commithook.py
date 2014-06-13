from ming.odm import ThreadLocalODMSession
from vulcanforge.migration.base import BaseMigration
from vulcanrepo.base.model import PostCommitHook
from vulcanrepo.svn.model import SVNRepository

from vulcanrepo.forgeport.hook import ForgePortHook


class AddForgeportCommitHook(BaseMigration):
    def run(self):
        count = 0
        pch, isnew = PostCommitHook.upsert(ForgePortHook)
        if isnew:
            self.write_output('Added ForgePortHook')
        for repo in SVNRepository.query.find():
            isnew = repo.upsert_post_commit_hook(pch)
            if isnew:
                count += 1
        self.write_output('Added ForgePortHook to {} repos'.format(count))
        ThreadLocalODMSession.flush_all()
