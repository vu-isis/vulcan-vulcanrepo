import shutil
import logging

from ming.odm import ThreadLocalODMSession
from pylons import tmpl_context as c

from vulcanforge.common.util.model import chunked_find
from vulcanforge.notification.model import Notification
from vulcanforge.project.model import Project
from vulcanforge.taskd import task

LOG = logging.getLogger(__name__)


@task
def init(**kwargs):
    c.app.repo.init()
    subject_text = "{} Repository {} created by {}"
    subject = subject_text.format(c.app.tool_label,
                                  c.app.config.options['mount_label'],
                                  c.user.get_pref('display_name'))
    Notification.post_user(
        c.user, c.app.repo, 'created', text='Repository created',
        subject=subject
    )
    ThreadLocalODMSession.flush_all()


@task
def clone(cloned_from_name, cloned_from_url):
    c.app.repo.init_as_clone(cloned_from_name, cloned_from_url)
    subject_text = "{} Repository {} created by {}"
    subject = subject_text.format(c.app.tool_label,
                                  c.app.config.options['mount_label'],
                                  c.user.get_pref('display_name'))
    Notification.post_user(
        c.user, c.app.repo, 'created', text='Repository created',
        subject=subject
    )
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
def purge_hook(hook_id):
    for projects in chunked_find(Project):
        for project in projects:
            for ac in project.app_configs:
                app = ac.load()
                if getattr(app, 'repo', None):
                    c.project = project
                    c.app = app
                    hooks = [hk for hk in c.app.repo.post_commit_hooks
                             if hk.plugin_id != hook_id]
                    if len(hooks) != len(c.app.repo.post_commit_hooks):
                        c.app.repo.post_commit_hooks = hooks
        ThreadLocalODMSession.flush_all()
