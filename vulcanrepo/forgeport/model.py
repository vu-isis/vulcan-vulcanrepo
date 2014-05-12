import json

from ming.odm import FieldProperty
from ming.odm.property import ForeignIdProperty

from vulcanrepo.base.model.derived import RepoDerivedObject
from vulcanforge.auth.model import User


class ForgeProjectFile(RepoDerivedObject):
    """
    These are designed to work with the ForgePort tool to parse

    """
    class __mongometa__:
        name = 'forgeproject_file'
        indexes = [
            'app_config_id',
            ('blob_spec.app_config_id', 'blob_spec.path',
             'blob_spec.version_id')
        ]

    name = FieldProperty(str, if_missing=None)
    creator_id = ForeignIdProperty(User, if_missing=None)

    @property
    def creator(self):
        if self.creator_id:
            return User.query.get(_id=self.creator_id)

    def get_last_modified_time(self):
        parent = self.blob.parent
        if parent:
            return parent.get_timestamp()

    def post_process(self):
        manifest_json = json.load(self.blob)
        self.name = manifest_json.get("name")
        if not self.creator_id and self.author_ids:
            self.creator_id = self.author_ids[0]

    @property
    def display_name(self):
        if self.name:
            return self.name
        else:
            return self.blob.parent.name
