from cPickle import dumps, loads

from vulcanforge.common.util.model import pymongo_db_collection
from vulcanforge.migration.base import BaseMigration

from vulcanrepo.base.model import PostCommitHook
from vulcanrepo.base.model.hook import VisualizerManager


class MigrateCommitHook(BaseMigration):
    def run(self):
        count = 0
        db, coll = pymongo_db_collection(PostCommitHook)
        for pch in coll.find({"cls": {"$exists": 1}}):
            try:
                cls = loads(pch['cls'])
            except (ImportError, AttributeError):
                if 'VisualizerManager' in str(pch['cls']):
                    cls = VisualizerManager
                else:
                    raise RuntimeError(
                        "Could not find post commit hook {}".format(
                            pch['cls']))
            pch['hook_cls'] = {
                'module': cls.__module__,
                'classname': cls.__name__
            }
            del pch['cls']
            coll.save(pch)
            count += 1

        self.write_output('Migrated {} commit hooks'.format(count))
