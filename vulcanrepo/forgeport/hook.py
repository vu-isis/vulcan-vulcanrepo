from vulcanrepo.base.model.hook import CommitPlugin
from vulcanrepo.forgeport.model import ForgeProjectFile


class ForgePortHook(CommitPlugin):
    description = u"Tracks .forgeproject.manifest.json files for forge port"
    FILENAME = '.forgeproject.manifest.json'

    def on_submit(self, commit):
        for blob in commit.files_added:
            if blob.name == self.FILENAME:
                ForgeProjectFile.from_blob(blob)
        for blob in commit.files_removed:
            if blob.name == self.FILENAME:
                forge_project = ForgeProjectFile.get_from_blob(blob)
                if forge_project:
                    forge_project.delete()