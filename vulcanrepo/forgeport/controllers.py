import os

from bson import ObjectId
from pylons import app_globals as g
from tg.decorators import expose
from vulcanforge.common.controllers import BaseController
from vulcanforge.project.model import AppConfig

from vulcanrepo.forgeport.model import ForgeProjectFile


class ForgePortRestController(BaseController):

    def _check_security(self):
        g.security.require_authenticated()

    def projects_for_app_config(self, app_config):
        repo = app_config.instantiate().repo
        ci = repo.latest()

        # find design projects
        owner_map = {}
        dp_query = {"app_config_id": app_config._id}
        for forge_project in ForgeProjectFile.query.find(dp_query):
            parent_path = os.path.dirname(forge_project.blob_spec.path) + '/'
            parent_dir = ci.get_path(parent_path)
            if not parent_dir:
                continue

            project_spec = {
                "name": forge_project.display_name,
                "svnUrl": repo.clone_url('https') + os.path.dirname(
                    forge_project.path),
                "lastModified": int(parent_dir.get_timestamp())
            }
            creator_id = forge_project.creator_id
            if creator_id not in owner_map:
                creator = forge_project.creator
                if creator:
                    username = creator.username
                    display_name = creator.display_name
                else:
                    username = 'unknown'
                    display_name = 'Unknown'
                owner_map[creator_id] = {
                    "userName": username,
                    "displayName": display_name,
                    "forgeProjects": []
                }
            owner_map[creator_id]["forgeProjects"].append(project_spec)

        return {
            "mountPoint": app_config.options.mount_point,
            "label": app_config.options.mount_label,
            "canWrite": g.security.has_access(app_config, 'write'),
            "forgeProjectOwners": owner_map.values(),
            "restUrl": '/rest' + app_config.url()
        }

    @expose('json')
    def get_projects(self, limit=100, **kwargs):
        try:
            limit = int(limit)
        except ValueError:
            limit = 100
        read_roles = '" OR "'.join(g.security.get_user_read_roles())
        query_list = [
            'type_s:"SVN Repository"',
            'read_roles:("{}")'.format(read_roles)
        ]
        repo_q = ' AND '.join(query_list)
        repo_result = g.search(repo_q, rows=limit)

        team_map = {}
        ac_ids = [ObjectId(d["app_config_id_s"]) for d in repo_result.docs]
        for ac in AppConfig.query.find({"_id": {"$in": ac_ids}}):
            repo_spec = self.projects_for_app_config(ac)

            if ac.project_id not in team_map:
                team_map[ac.project_id] = {
                    "shortName": ac.project.shortname,
                    "name": ac.project.name,
                    "repositories": []
                }

            team_map[ac.project_id]["repositories"].append(repo_spec)

        return {
            "Teams": team_map.values()
        }