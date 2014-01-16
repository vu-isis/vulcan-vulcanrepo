from itertools import chain

from ming.odm import ThreadLocalODMSession
from pylons import app_globals as g
from vulcanforge.common.model.session import repository_orm_session
from vulcanforge.migration.base import BaseMigration
from vulcanrepo.base.model import PostCommitHook
from vulcanrepo.base.model.hook import VisualizerHook
from vulcanrepo.git.model.git_repo import GitRepository
from vulcanrepo.svn.model.svn import SVNRepository


class MigrateVisualizerInfrastructure(BaseMigration):
    def run(self):
        # add on_upload hook to repos
        count = 0
        pch, isnew = PostCommitHook.upsert(VisualizerHook)
        if isnew:
            self.write_output('Added VisualizerHook')
        iter_repo = chain(SVNRepository.query.find(),
                          GitRepository.query.find())
        for repo in iter_repo:
            isnew = repo.upsert_post_commit_hook(pch)
            if isnew:
                count += 1
        self.write_output('Added VisualizerHook to {} repos'.format(count))
        ThreadLocalODMSession.flush_all()
        self.close_sessions()

        # kill alternate resources
        count = 0
        db = repository_orm_session.impl.bind.db
        coll = db.repo_alternate
        for alt_doc in coll.find({"ondemand.key": {"$exists": 1}}):
            key = g.s3_bucket.get_key(alt_doc["ondemand"]["key"])
            if key:
                key.delete()
                count += 1
        coll.drop()
        self.write_output("Cleared {} alternate resources".format(count))
