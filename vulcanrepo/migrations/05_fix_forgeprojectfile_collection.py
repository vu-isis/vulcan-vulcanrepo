from vulcanforge.common.util.model import pymongo_db_collection
from vulcanforge.migration.base import BaseMigration
from vulcanrepo.base.model.derived import RepoDerivedObject
from vulcanrepo.forgeport.model import ForgeProjectFile


class FixForgeProjectFileCollection(BaseMigration):
    def run(self):
        count = 0
        db, coll0 = pymongo_db_collection(RepoDerivedObject)
        db, coll1 = pymongo_db_collection(ForgeProjectFile)
        for doc in coll0.find({"creator_id": {"$exists": 1}}):
            del doc['_id']
            coll1.insert(doc)
            count += 1
        self.write_output("Fixed {} ForgeProjectFile dooders".format(count))
