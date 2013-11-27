from itertools import chain

from vulcanforge.migration.base import BaseMigration
from vulcanrepo.base.model import PostCommitHook
from vulcanrepo.base.model.hook import VisualizerHook
from vulcanrepo.git.model.git_repo import GitRepository
from vulcanrepo.svn.model.svn import SVNRepository


class AddVisualizerHook(BaseMigration):
    def run(self):
        count = 0
        pch = PostCommitHook.upsert(VisualizerHook)
        iter_repo = chain(SVNRepository.query.find(),
                          GitRepository.query.find())
        for repo in iter_repo:
            isnew = repo.upsert_post_commit_hook(pch)
            if isnew:
                count += 1
        self.write_output('Added VisualizerHook to {} repos'.format(count))
