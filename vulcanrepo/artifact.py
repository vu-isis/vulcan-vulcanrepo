import re
import logging

import bson
from pylons import app_globals as g, tmpl_context as c
from vulcanforge.artifact.api import ArtifactAPI
from vulcanforge.artifact.model import Shortlink
from vulcanforge.project.model import Project

LOG = logging.getLogger(__name__)

REPO_INDEX_ID_RE = re.compile(r'^Repo\.')


def repo_get_by_index_id(index_id, match=None):
    artifact = None
    try:
        _, ac_id, ci_oid, path = index_id.split('.', 3)
        with g.context_manager.push(app_config_id=bson.ObjectId(ac_id)):
            ci = c.app.repo.commit(ci_oid)
            if ci:
                artifact = ci.get_path(path)
    except Exception:
        LOG.warn('Error looking up repo? index_id {}'.format(index_id))
    return artifact

REPO_SHORTLINK_RE = re.compile(r'^\((?P<commit>[a-z0-9]+)\)(?P<path>/.*)')


def _get_by_slink_with_context(repo, ci_oid, path):
    ci = repo.commit(ci_oid)
    if ci:
        return ci.get_path(path)


def repo_get_by_shortlink(parsed_link, match):
    artifact = None
    ci_oid, path = match.group('commit'), match.group('path')
    project = Project.by_shortname(parsed_link['project'])
    if project:
        if parsed_link['app']:
            app = project.app_instance(parsed_link['app'])
            if app and hasattr(app, 'repo'):
                artifact = _get_by_slink_with_context(app.repo, ci_oid, path)
        else:
            for ac in project.app_configs:
                app = project.app_instance(ac)
                if hasattr(app, 'repo'):
                    artifact = _get_by_slink_with_context(
                        app.repo, ci_oid, path)
                    if artifact:
                        break
    return artifact


def repo_ref_id_by_link(parsed_link, match, upsert=True):
    ref_id = None
    artifact = repo_get_by_shortlink(parsed_link, match)
    if artifact:
        ref_id = artifact.index_id()
        if upsert:
            Shortlink.from_artifact(artifact)
    return ref_id


REPO_INDEX_ID = ArtifactAPI.INDEX_ID_EPHEMERALS.copy()
REPO_INDEX_ID.update({
    REPO_INDEX_ID_RE: repo_get_by_index_id
})

REPO_SHORTLINK = ArtifactAPI.SHORTLINK_EPHERMERALS.copy()
REPO_SHORTLINK.update({
    REPO_SHORTLINK_RE: {
        'ref_id': repo_ref_id_by_link,
        'artifact': repo_get_by_shortlink
    }
})


class RepoArtifactAPI(ArtifactAPI):
    INDEX_ID_EPHEMERALS = REPO_INDEX_ID
    SHORTLINK_EPHERMERALS = REPO_SHORTLINK
