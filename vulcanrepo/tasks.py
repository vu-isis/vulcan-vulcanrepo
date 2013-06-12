import shutil
import logging

from ming.odm import ThreadLocalODMSession
from pylons import tmpl_context as c

from vulcanforge.common.exceptions import ForgeError
from vulcanforge.artifact.model import ArtifactProcessor
from vulcanforge.notification.model import Notification
from vulcanforge.taskd import task

from vulcanrepo.base.model import RepoAlternate

LOG = logging.getLogger(__name__)


@task
def init(**kwargs):
    c.app.repo.init()
    Notification.post_user(
        c.user, c.app.repo, 'created', text='Repository created')
    ThreadLocalODMSession.flush_all()


@task
def clone(cloned_from_name, cloned_from_url):
    c.app.repo.init_as_clone(cloned_from_name, cloned_from_url)
    Notification.post_user(
        c.user, c.app.repo, 'created', text='Repository created')
    ThreadLocalODMSession.flush_all()


@task
def refresh(**kwargs):
    c.app.repo.refresh()


@task
def run_commit_hooks(commits=None):
    if commits == "all":
        c.app.repo.run_batched_post_commit_hooks()
    else:
        c.app.repo.run_post_commit_hooks(commits)


@task
def uninstall(**kwargs):
    from vulcanrepo.base.app import RepositoryApp
    repo = c.app.repo
    if repo is not None:
        shutil.rmtree(repo.full_fs_path, ignore_errors=True)
        repo.delete()
    super(RepositoryApp, c.app).uninstall(c.project)


@task
def nop():
    log = logging.getLogger(__name__)
    log.info('nop')


@task
def process_file(processor_name, context, commit, path, force=False):
    LOG.info('processing file at {} using {} processor'.format(
        path, processor_name))

    ci = c.app.repo.commit(commit)
    file = ci.get_path(path)
    if not file:
        raise ForgeError('file not found at {}:{}'.format(commit, path))

    found = False
    if not force:
        identical_alt = RepoAlternate.query.find({
            'content_hash': file.get_content_hash(),
            'resources.{}'.format(context): {'$exists': 1}
        }).first()
        if identical_alt:
            file.set_alt_resource(
                context, identical_alt.resources[context], flush=True)
            found = True

    if not found:
        ArtifactProcessor.process(processor_name, file, context)
