from formencode.variabledecode import variable_decode
from ming.odm import ThreadLocalODMSession
from tg import config
from vulcanforge.command import base
from vulcanforge.common.util.filesystem import import_object

from vulcanrepo.base.model import PostCommitHook


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
                PostCommitHook.from_object(hook_cls)
        ThreadLocalODMSession.flush_all()