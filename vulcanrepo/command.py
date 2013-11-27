from formencode.variabledecode import variable_decode
from ming.odm import ThreadLocalODMSession
from pylons import app_globals as g, tmpl_context as c
from tg import config
from vulcanforge.command import base
from vulcanforge.common.util.filesystem import import_object
from vulcanforge.neighborhood.model import Neighborhood
from vulcanforge.visualize.model import VisualizerConfig

from vulcanrepo.base.model import PostCommitHook
from vulcanrepo.base.model.hook import VisualizerManager


class SyncCommitHooks(base.Command):
    summary = 'Initialize Default Commit Hooks in the Database'
    parser = base.Command.standard_parser(verbose=True)
    parser.add_option(
        '-s', '--shortname', dest='shortname',
        help="shortname of commit hook to sync (defaults to all)")
    parser.add_option(
        '-u', '--update_existing', dest='update_existing',
        help="Update existing commit hook if one already exists with a given"
             "shortname")

    def command(self):
        self.basic_setup()
        decoded = variable_decode(config)
        opts = decoded['commit_hook']
        for shortname, path in opts.items():
            if self.options.shortname and shortname != self.options.shortname:
                continue
            hook_inst = PostCommitHook.query.get(shortname=shortname)
            if hook_inst and not self.options.update_existing:
                continue
            hook_cls = import_object(path)
            hook_spec = {
                "module": hook_cls.__module__,
                "classname": hook_cls.__name__
            }
            if hook_inst:
                if hook_inst.hook_cls != hook_spec:
                    hook_inst.hook_cls = hook_spec
            else:
                PostCommitHook.from_object(hook_cls, shortname=shortname)
        ThreadLocalODMSession.flush_all()


class AddRepoVisualizerHook(base.Command):
    summary = 'Add a post commit hook to sync a repo with a visualizer'
    usage = ('<ini file> [options] <visualizer_shortname> '
             '<project_shortname>.<repo_mount_point>')
    min_args = 3
    max_args = 3
    parser = base.Command.standard_parser(verbose=True)
    parser.add_option(
        '-n', '--neighborhood', dest='neighborhood',
        help='url_prefix of neighborhood'
    )
    parser.add_option(
        '--visualizer', dest='visualizer', default=None,
        help='path to visualizer class (default to S3Hosted)'
    )
    parser.add_option(
        '-b', '--branch', dest='branch', default='master',
        help='restrict to this branch for visualizer updates (git only)'
    )

    def _get_visualizer_path(self, vis_shortname):
        decoded = variable_decode(config)
        visopts = decoded['visualizer']
        visualizer = None
        for shortname, path in visopts.items():
            if shortname == vis_shortname:
                visualizer = path
                break
        return visualizer

    def command(self):
        self.basic_setup()
        if self.options.neighborhood:
            neighborhood = Neighborhood.by_prefix(self.options.neighborhood)
        else:
            neighborhood = None
        shortname, mount_point = self.args[2].split('.')
        g.context_manager.set(shortname, mount_point,
                              neighborhood=neighborhood)
        if not c.app or not c.app.repo:
            raise RuntimeError(
                "Repo at {}.{} not found".format(shortname, mount_point))

        vis_shortname = self.args[1]
        # insert visualizer if necessary (if None, the commit hook will take
        # care of initializing it)
        if not VisualizerConfig.query.get(shortname=vis_shortname):
            visualizer_path = self.options.visualizer or \
                self._get_visualizer_path(vis_shortname)
            if visualizer_path:
                self.log.info('Adding visualizer at %s', visualizer_path)
                visualizer = import_object(visualizer_path)
                VisualizerConfig.from_visualizer(
                    visualizer, shortname=vis_shortname)

        # upsert post commit hook for visualizer management
        pch, isnew = PostCommitHook.upsert(
            VisualizerManager, shortname="visualizer_manager")
        if isnew:
            self.log.info('Added visualizer_manager post commit hook')
        ThreadLocalODMSession.flush_all()

        # add post commit hook to repository
        hook_kwargs = {}
        if c.app.repo.repo_id != 'svn':
            hook_kwargs['restrict_branch_to'] = self.options.branch
        isnew = c.app.repo.upsert_post_commit_hook(
            pch, args=[vis_shortname], kwargs=hook_kwargs)

        ThreadLocalODMSession.flush_all()

        # run on latest commit
        if isnew:
            ci = c.app.repo.latest() if c.app.repo.repo_id == 'svn' else \
                c.app.repo.latest(self.options.branch)
            if ci:
                self.log.info('Running visualizer post commit hook on %s',
                              ci.object_id)
                pch.run([ci], args=[vis_shortname], kwargs=hook_kwargs)

        ThreadLocalODMSession.flush_all()
