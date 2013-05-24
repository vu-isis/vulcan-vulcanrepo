import os
import shutil
import logging
import subprocess
import pymongo
from cStringIO import StringIO
from datetime import datetime
import hashlib
from itertools import chain, ifilter

try:
    import pysvn
except ImportError:
    pysvn = None
from ming.base import Object
from ming.odm import FieldProperty, session
from ming.utils import LazyProperty
from pylons import tmpl_context as c
import tg
from vulcanforge.common import helpers as h
from vulcanforge.auth.model import User

from vulcanrepo.base.model import (
    RepositoryFolder,
    RepositoryFile,
    Repository,
    Commit
)
from vulcanrepo.exceptions import RepoError

log = logging.getLogger(__name__)


class SVNError(RepoError):
    pass


def make_content_object(info, ci):
    result = None
    path = info.repos_path
    if path.startswith('//'):
        path = path[1:]
    if info.kind == pysvn.node_kind.dir:
        if not path.endswith('/'):
            path += '/'
        result = SVNFolder(ci, path)
        result._info = info
    elif info.kind == pysvn.node_kind.file:
        result = SVNFile(ci, path)
        result._info = info
    return result


class SVNCommit(Commit):

    class __mongometa__:
        name = 'svn_commit'
        indexes = [
            'repository_id',
            ('repository_id', 'commit_num'),
        ]

    commit_num = FieldProperty(int)

    @classmethod
    def new_by_object_id(cls, object_id, repository_id):
        new = super(SVNCommit, cls).new_by_object_id(object_id, repository_id)
        _, ci_num_s = object_id.split(':')
        new.commit_num = int(ci_num_s)
        return new

    @LazyProperty
    def parent(self):
        if self.commit_num > 1:
            return self.__class__.query.get(
                commit_num=self.commit_num - 1,
                repository_id=self.repository_id
            )

    @LazyProperty
    def child(self):
        return self.__class__.query.get(
            commit_num=self.commit_num + 1,
            repository_id=self.repository_id
        )

    def context(self):
        return {
            'prev': [self.parent] if self.parent else [],
            'next': [self.child] if self.child else []
        }

    @LazyProperty
    def repo(self):
        return SVNRepository.query.get(_id=self.repository_id)

    @LazyProperty
    def user(self):
        if self.authored.name:
            return User.by_username(self.authored.name)
        return super(SVNCommit, self).user

    @LazyProperty
    def svn_revision(self):
        return pysvn.Revision(pysvn.opt_revision_kind.number, self.commit_num)

    @LazyProperty
    def tree(self):
        return SVNFolder(self, '/')

    @property
    def url_rev(self):
        return str(self.commit_num)

    def shorthand_id(self):
        return 'r{}'.format(self.commit_num)

    def log(self, skip, count, path=None, **kw):
        """
        NOTE: this can be made more efficient in paging situations by
        setting rev start based on the last commit viewed on the prev page.

        :param skip: int
        :param count: int
        :param path: str
        :return: list of SVNCommit objects

        """
        if self.commit_num > 1 or 'revision_end' in kw:
            url = self.repo.svn_url
            if path:
                url += path
            try:
                logs = self.repo.svn.log(
                    url,
                    revision_start=self.svn_revision,
                    limit=skip + count,
                    **kw
                )
            except pysvn.ClientError:
                return []

            ci_nums = [log.revision.number for log in logs[skip:skip + count]]
            cursor = SVNCommit.query.find({
                "repository_id": self.repository_id,
                "commit_num": {"$in": ci_nums}
            })
            return cursor.sort("commit_num", pymongo.DESCENDING).all()
        else:
            return [self][skip:]

    @property
    def files_removed(self):
        """NOTE: returned with context of parent commit"""
        removed = []
        removed_paths = set()
        for path in self.diffs.removed:
            if path not in removed_paths:
                removed_paths.add(path)
                obj = self.parent.get_path(path)
                if obj.kind == 'File':
                    removed.append(obj)
                else:
                    for child in obj.find_files():
                        if child.path not in removed_paths:
                            removed.append(child)
                            removed_paths.add(child.path)
        return removed

    def get_path(self, path):
        result = None
        if not path.startswith('/'):
            path = '/' + path
        try:
            info = self.repo.svn.list(
                self.repo.svn_url + path,
                revision=self.svn_revision,
                peg_revision=self.svn_revision,
                recurse=False
            )
        except pysvn.ClientError:
            pass
        else:
            result = make_content_object(info[0][0], self)
            if result.kind == 'Folder':
                result._listing = info
        return result


class SVNRepository(Repository):
    commit_cls = SVNCommit

    class __mongometa__:
        name = 'svn-repository'

    head = FieldProperty(dict(name=str, object_id=str), if_missing=None)

    tool_name = 'SVN'
    repo_id = 'svn'
    type_s = 'SVN Repository'
    MAX_MEM_READ = 50 * 10 ** 6
    url_map = {
        'ro': 'http://svn.{host}{path}/trunk',
        'rw': 'svn+ssh://{username}@{host}/scm-repo{path}/trunk',
        'https': 'https://{username}@{host}/scm-repo{path}/trunk',
        'https_anon': 'https://{host}/scm-repo{path}/trunk'
    }

    @LazyProperty
    def svn(self):
        return pysvn.Client()

    @LazyProperty
    def svn_url(self):
        return 'file://%s/%s' % (self.fs_path, self.name)

    def init(self):
        fullname = self._setup_paths()
        log.info('svn init %s', fullname)
        if os.path.exists(fullname):
            shutil.rmtree(fullname)
        subprocess.call(
            ['svnadmin', 'create', self.name],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=self.fs_path)
        self._setup_hooks()
        self._setup_customizations()
        self.status = 'ready'

    def clone_command(self, category, username=''):
        if category in ('ro', 'https_anon'):
            cmd = 'svn checkout {source_url} {dest_path}'
        else:
            if not username and c.user not in (None, User.anonymous()):
                username = c.user.username
            cmd0 = 'svn checkout --username={username}'.format(
                username=username)
            cmd = cmd0 + ' {source_url} {dest_path}'
        return cmd.format(
            source_url=self.clone_url(category, username),
            dest_path=self.suggested_clone_dest_path()
        )

    def clone_from(self, source_url):
        """Initialize a repo as a clone of another using svnsync"""
        fullname = self._setup_paths()
        log.info('Initialize %r as a clone of %s', self, source_url)
        if os.path.exists(fullname):
            shutil.rmtree(fullname)

        try:
            subprocess.check_output(
                ['svnadmin', 'hotcopy', source_url, self.full_fs_path])
        except subprocess.CalledProcessError, e:
            raise SVNError(
                'Exception performing svnadmin hotcopy -- {}'.format(e.output))
        self._setup_hooks()
        # self._setup_customizations()

        self.status = 'initializing'
        session(self.__class__).flush()
        log.info('... %r cloned, analyzing', self)
        self.refresh(update_status=False)
        self.status = 'ready'
        log.info('... %s ready', self)
        session(self.__class__).flush()

    def refresh_heads(self):
        info = self.svn.info2(
            self.svn_url,
            revision=pysvn.Revision(pysvn.opt_revision_kind.head),
            recurse=False)[0][1]
        if info.rev.number:
            oid = self._oid(info.rev.number)
            self.head = Object(name=None, object_id=oid)
            session(self.__class__).flush()

    def latest(self):
        if self.head:
            ci = SVNCommit.query.get(object_id=self.head.object_id)
            if ci:
                ci.set_context(self)
            return ci

    def commit(self, rev=None):
        if rev in ('head', None):
            return self.latest()

        if isinstance(rev, int) or rev.isdigit():
            rev = self._oid(rev)
        if rev.startswith('r') and rev[1:].isdigit():
            rev = self._oid(rev[1:])
        result = SVNCommit.query.get(object_id=rev)
        if result is not None:
            result.set_context(self)
        return result

    def new_commits(self, all_commits=False):
        if not self.head:
            return []
        head_revno = self._revno(self.head.object_id)
        oids = [self._oid(revno) for revno in range(1, head_revno + 1)]
        if all_commits:
            return oids
        cursor = SVNCommit.query.find({'repository_id': self._id})
        seen_oids = set(ci.object_id for ci in cursor)
        return list(set(oids).difference(seen_oids))

    def refresh_commit(self, ci):
        rev = ci.svn_revision
        try:
            log_entry = self.svn.log(
                self.svn_url,
                revision_start=rev,
                limit=1,
                discover_changed_paths=True)[0]
        except pysvn.ClientError:  # pragma no cover
            log.warn(
                'ClientError processing %r %r, treating as empty',
                ci, self, exc_info=True)
            log_entry = Object(date='', message='', changed_paths=[])

        # Save commit metadata
        ci.authored = Object(
            name=log_entry.get('author', '--none--'),
            email='',
            date=datetime.utcfromtimestamp(log_entry.date)
        )
        ci.message = log_entry.message

        # Save diff info
        ci.diffs.added = []
        ci.diffs.removed = []
        ci.diffs.changed = []
        ci.diffs.copied = []
        lst = dict(
            A=ci.diffs.added,
            D=ci.diffs.removed,
            M=ci.diffs.changed,
            R=ci.diffs.changed)
        parent_rev = pysvn.Revision(
            pysvn.opt_revision_kind.number,
            ci.commit_num - 1)
        for path in log_entry.changed_paths:
            p = path.path
            rev = parent_rev if path.action == 'D' else ci.svn_revision
            is_file = self._is_file(p, rev)
            if not is_file:
                p += '/'
            if path.copyfrom_path:
                from_p = path.copyfrom_path
                if not is_file:
                    from_p += '/'
                ci.diffs.copied.append({
                    'old': h.really_unicode(from_p),
                    'new': h.really_unicode(p)
                })
            else:
                lst[path.action].append(h.really_unicode(p))

    def _is_file(self, path, rev=None):
        l_info = self.svn.list(
            self.svn_url + path,
            revision=rev,
            peg_revision=rev,
            recurse=False)[0][0]
        return l_info.kind == pysvn.node_kind.file

    def _setup_hooks(self):
        """Set up the post-commit and pre-revprop-change hooks"""
        text = self.post_receive_template.substitute(
            url=tg.config.get(
                'cloud_url',
                tg.config.get('base_url', 'http://localhost:8080')
            ) + '/auth/refresh_repo' + self.url()
        )
        fn = os.path.join(self.full_fs_path, 'hooks', 'post-commit')
        with open(fn, 'wb') as fp:
            fp.write(text)
        os.chmod(fn, 0755)
        fn = os.path.join(
            self.fs_path, self.name, 'hooks', 'pre-revprop-change')
        with open(fn, 'wb') as fp:
            fp.write('#!/bin/sh\n')
        os.chmod(fn, 0755)

    def _setup_customizations(self):
        # certain clients (e.g., Mac OS X 10.6.8 with Subversion 1.6.16) have
        # problems with rep-sharing,
        # so turn off this space vs.time optimization
        path = os.path.join(self.full_fs_path, 'db', 'fsfs.conf')
        with open(path, "a") as f:
            f.write("enable-rep-sharing = false\n")

    def _revno(self, oid):
        return int(oid.split(':')[1])

    def _oid(self, revno):
        return '{}:{}'.format(self._id, revno)

    def add_file(self, path, dest, msg='', author=None):
        """
        Add a file to the repository and commit the changes

        @param path: path to file
        @param dest: path to destination relative to repository root
        @param msg: log msg for commit
        @param branch: branch or rev
        @param author: str  author (defaults to current user display name)
        @return: new commit object

        """
        dest_url = self.svn_url + dest + os.path.basename(path)
        rev = self.svn.import_(path, dest_url, msg)
        if author:
            self.svn.revpropset("svn:author", author, dest_url, revision=rev)
        self.refresh()


class SVNContentMixIn(object):
    # these are set by the mixee
    repo = None
    commit = None
    path = None
    _info = None

    @property
    def svn_url(self):
        return self.repo.svn_url + self.path

    @property
    def last_commit_num(self):
        return self._info['created_rev'].number

    @property
    def version_id(self):
        return str(self.last_commit_num)

    def get_last_commit(self):
        return SVNCommit.query.get(
            commit_num=self.last_commit_num,
            repository_id=self.commit.repository_id
        )

    @LazyProperty
    def prev_commit(self):
        ci = self.commit.log(1, 1, path=self.path)
        if ci:
            return ci[0]

    @LazyProperty
    def next_commit(self):
        head_num = int(self.repo.head.object_id.split(':')[1])
        if head_num > self.commit.commit_num:
            rev_end = pysvn.Revision(pysvn.opt_revision_kind.number, head_num)
            log = self.commit.log(1, 1, path=self.path, revision_end=rev_end)
            if log:
                return log[0]


class SVNFolder(RepositoryFolder, SVNContentMixIn):

    @LazyProperty
    def _info(self):
        return self._listing[0][0]

    @LazyProperty
    def _listing(self):
        rev = self.commit.svn_revision
        return self.repo.svn.list(
            self.svn_url, revision=rev, peg_revision=rev, recurse=False)

    def __iter__(self):
        for l_info in self._listing[1:]:
            obj = make_content_object(l_info[0], self.commit)
            if obj.kind == 'File':
                obj.parent = self
            yield obj

    def ls_commits(self, include_self=False, paths=None):
        data = {}
        commits = {}
        if paths is None:
            objs = chain([self], iter(self)) if include_self else iter(self)
        else:
            objs = ifilter(None, (self[path] for path in paths))
            if include_self:
                objs = chain([self], objs)
        for obj in objs:
            # last commit info
            revno = obj._info['created_rev'].number
            if revno in commits:
                lc = commits[revno]
            else:
                ci = obj.get_last_commit()
                lc = ci.info()
                commits[revno] = lc
            data[obj.path] = lc
        return data

    def find_files(self):
        """Find all file paths recursively beneath this folder"""
        rev = self.commit.svn_revision
        listing = self.repo.svn.list(
            self.svn_url,
            revision=rev,
            peg_revision=rev,
            depth=pysvn.depth.infinity)
        for info, _ in listing:
            if info.kind == pysvn.node_kind.file:
                yield make_content_object(info, self.commit)


class SVNFile(RepositoryFile, SVNContentMixIn):
    folder_cls = SVNFolder

    def __init__(self, *args, **kw):
        self._content_hash = None
        super(SVNFile, self).__init__(*args, **kw)

    @LazyProperty
    def _info(self):
        rev = self.commit.svn_revision
        l_info = self.repo.svn.list(
            self.svn_url, revision=rev, peg_revision=rev, recurse=False)[0][0]
        return l_info

    def open(self):
        return StringIO(self.read())

    def read(self):
        return self.repo.svn.cat(
            self.svn_url,
            revision=self.commit.svn_revision,
            peg_revision=self.commit.svn_revision
        )

    @LazyProperty
    def size(self):
        return self._info["size"]

    def get_content_hash(self):
        if self._content_hash is None:
            md5 = hashlib.md5()
            md5.update(self.read())
            self._content_hash = md5.hexdigest()
        return self._content_hash
