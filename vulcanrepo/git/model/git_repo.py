import os
import shutil
import logging
import subprocess
from datetime import datetime, time
from collections import deque
from itertools import chain, ifilter

from ming.base import Object
from ming.odm import session, FieldProperty
from ming import schema as S
from ming.utils import LazyProperty
import pymongo
try:
    import git
except ImportError:
    git = None

from pylons import tmpl_context as c, app_globals as g
import tg

from vulcanforge.common import helpers as h
from vulcanforge.cache.decorators import cache_str
from vulcanforge.artifact.model import VersionedArtifact
from vulcanforge.auth.model import User

from vulcanrepo.base.model import (
    RepositoryFile,
    RepositoryFolder,
    Commit,
    Repository
)

LOG = logging.getLogger(__name__)
GIT_ADD_SCRIPT = os.path.join(
    __file__, os.path.pardir, 'scripts/git-commit-to-bare.bash')


def make_content_object(obj, ci):
    """Makes a GitFile or GitFolder object

    :param obj git.Blob || git.Tree
    :param ci GitCommit
    :return GitFile || GitFolder

    """
    result = None
    if obj.type == 'blob':
        result = GitFile(ci, u'/' + obj.path)
        result._obj = obj
    elif obj.type == 'tree':
        result = GitFolder(ci, u'/' + obj.path)
        result._obj = obj
    return result


class GitCommit(Commit):

    class __mongometa__:
        name = 'git_commit'
        indexes = [('parent_ids', 'repository_id'),
                   ("committed.date", pymongo.DESCENDING)]

    parent_ids = FieldProperty([str])
    committed = FieldProperty(dict(
        name=str,
        email=str,
        date=datetime
    ))

    @LazyProperty
    def repo(self):
        return GitRepository.query.get(_id=self.repository_id)

    @LazyProperty
    def parents(self):
        if self.parent_ids:
            return self.__class__.query.find({
                'object_id': {'$in': self.parent_ids},
                'repository_id': self.repository_id
            }).all()
        return []

    @LazyProperty
    def children(self):
        return self.__class__.query.find({
            'parent_ids': self.object_id,
            'repository_id': self.repository_id
        }).all()

    def context(self):
        return {
            'prev': self.parents,
            'next': self.children
        }

    @LazyProperty
    def _obj(self):
        return self.repo.git_repo.commit(self.object_id)

    def shorthand_id(self):
        return '{}'.format(self.object_id[:6])

    def log(self, skip, count, path=None):
        args = ['-{}'.format(count), '--skip={}'.format(skip), self.object_id]
        if path:
            path = path.strip('/')
            if path:
                args.extend(['--', path])
        oids = self.repo.git_repo.git.rev_list(*args)
        if oids:
            return self.__class__.query.find({
                "object_id": {"$in": oids.split('\n')},
                "repository_id": self.repository_id
            }).sort("committed.date", pymongo.DESCENDING).all()
        return []

    @LazyProperty
    def tree(self):
        return GitFolder(self, u'/')

    def get_obj_from_path(self, path):
        path = path.strip(u'/')

        if not path:
            return self._obj.tree

        rev = u'{}:{}'.format(self.object_id, path)
        try:
            obj = self.repo.git_repo.rev_parse(rev)
        except KeyError:
            return None
        return obj

    def get_path(self, path):
        if path == u'/':
            return self.tree

        if verify:
            obj = self.get_obj_from_path(path)
            if obj:
                return make_content_object(obj, self)
        else:
            return GitFile(self, path)

    @property
    def files_removed(self):
        """NOTE: returned with context of parent commit"""
        removed = []
        removed_paths = set()
        for path in self.diffs.removed:
            if path not in removed_paths:
                removed_paths.add(path)
                obj = None
                for parent in self.parents:
                    obj = parent.get_path(path)
                    if obj:
                        break
                if obj.kind == 'File':
                    removed.append(obj)
                else:
                    for child in obj.find_files():
                        if child.path not in removed_paths:
                            removed.append(child)
                            removed_paths.add(child.path)
        return removed

    def branches(self):
        s = self.repo.git_repo.git.branch(contains=self.object_id)
        return [br.strip(' *') for br in s.split('\n')]


class GitRepository(Repository):
    commit_cls = GitCommit

    class __mongometa__:
        name = 'git-repository'

    tool_name = 'Git'
    repo_id = 'git'
    type_s = 'Git Repository'
    url_map = {
        'ro': 'http://{host}{path}',
        'rw': 'ssh://{username}@{host}{path}',
        'https': 'https://{username}@{host}{path}',
        'https_anon': 'https://{host}{path}'
    }

    branches = FieldProperty(
        [dict(name=str, object_id=str, count=int)], if_missing=[])
    heads = FieldProperty(
        [dict(name=str, object_id=str, count=int)], if_missing=[])
    repo_tags = FieldProperty(
        [dict(name=str, object_id=str, count=int)], if_missing=[])

    @property
    def url_name(self):
        return self.name[:-4]  # strips .git from end of name

    def merge_command(self, merge_request):  # pragma no cover
        """
        Return the command to merge a given commit to a given target branch

        """
        return 'git checkout %s;\ngit fetch git://%s %s;\ngit merge %s' % (
            merge_request.target_branch,
            merge_request.downstream_repo_url,
            merge_request.downstream.commit_id,
            merge_request.downstream.commit_id)

    @LazyProperty
    def git_repo(self):
        try:
            return git.Repo(self.full_fs_path)
        except (git.exc.NoSuchPathError,
                git.exc.InvalidGitRepositoryError), err:  # pragma no cover
            LOG.error('Problem looking up repo: %r', err)
            return None

    def init(self):
        fullname = self._setup_paths()
        LOG.info('git init %s', fullname)
        if os.path.exists(fullname):
            shutil.rmtree(fullname)
        repo = git.Repo.init(
            path=fullname, mkdir=True, quiet=True, bare=True, shared='all')
        self.git_repo = repo
        self._setup_hooks()
        self.status = 'ready'

    def clone_from(self, source_url):
        """Initialize a repo as a clone of another"""
        fullname = self._setup_paths(create_repo_dir=False)
        if os.path.exists(fullname):
            shutil.rmtree(fullname)
        LOG.info('Initialize %r as a clone of %s', self, source_url)
        repo = git.Repo.clone_from(source_url, to_path=fullname, bare=True)
        self.git_repo = repo
        self._setup_hooks()
        self.status = 'initializing'
        session(self.__class__).flush()
        LOG.info('... %r cloned, analyzing', self)
        self.refresh(update_status=False)
        self.status = 'ready'
        LOG.info('... %s ready', self)
        session(self.__class__).flush()

    def clone_command(self, category, username=''):
        return 'git clone {source_url} {dest_path}'.format(
            source_url=self.clone_url(category, username),
            dest_path=self.suggested_clone_dest_path()
        )

    def latest(self, branch='master'):
        try:
            return self.commit(branch)
        except Exception:  # pragma no cover
            LOG.exception('Cannot get latest commit for a branch %s' % branch)
            return None

    def _commit_obj(self, rev):
        obj = None
        try:
            obj = self.git_repo.rev_parse(rev)
            if obj.type == 'tag':
                obj = obj.object
        except (git.exc.BadObject, ValueError):
            pass
        return obj

    def _find_head(self, name):
        for head in self.heads:
            if head.name == name:
                return head

    def commit(self, rev=None):
        """
        Return a Commit object.

        rev can be object_id or a branch/tag name

        """
        result = None
        if rev is None:
            rev = 'master'
        git_ci = self._commit_obj(rev)
        if git_ci:
            result = GitCommit.query.get(
                object_id=git_ci.hexsha,
                repository_id=self._id
            )
            if not result:
                head = self._find_head(rev)
                if head:
                    result = GitCommit.query.get(
                        object_id=head.object_id,
                        repository_id=self._id
                    )
            if result is not None:
                result.set_context(self)
            else:
                LOG.warn('Commit {} Not Found in Repository {}'.format(
                         git_ci.hexsha, self._id))

        return result

    def new_commits(self, all_commits=False):
        """Finds new commits in topological sort order"""
        seen = set()
        new = deque([])
        to_visit = deque(hd.commit for hd in self.git_repo.heads)
        while to_visit:
            obj = to_visit.popleft()
            if not obj.hexsha in seen:
                isnew = True
                if not all_commits:
                    ci = GitCommit.query.get(
                        object_id=obj.hexsha,
                        repository_id=self._id
                    )
                    isnew = ci is None
                if isnew:
                    new.appendleft(obj.hexsha)
                    to_visit.extend(obj.parents)
                seen.add(obj.hexsha)
        return list(new)

    def own_commits(self):
        """Copy commits from previous repo to this repo"""
        all_commit_ids = self.new_commits(True)
        coll = session(GitCommit).impl.bind.db.git_commit
        cursor = coll.find({
            'object_id': {'$in': all_commit_ids},
            'repository_id': {'$ne': self._id}
        })
        for ci_doc in cursor:
            del ci_doc['_id']
            ci_doc.update({
                'repository_id': self._id,
                'app_config_id': self.app_config_id
            })
            coll.save(ci_doc)

    def refresh_heads(self):
        self.heads = [
            Object(name=head.name, object_id=head.commit.hexsha)
            for head in self.git_repo.heads if head.is_valid()]
        self.branches = [
            Object(name=head.name, object_id=head.commit.hexsha)
            for head in self.git_repo.branches if head.is_valid()]
        self.repo_tags = [
            Object(name=tag.name, object_id=tag.commit.hexsha)
            for tag in self.git_repo.tags if tag.is_valid()]
        session(self.__class__).flush()

    def refresh_commit(self, ci):
        obj = self.git_repo.commit(ci.object_id)
        ci._obj = obj

        # Save commit metadata
        ci.committed = Object(
            name=h.really_unicode(obj.committer.name),
            email=h.really_unicode(obj.committer.email),
            date=datetime.utcfromtimestamp(obj.committed_date))
        ci.authored = Object(
            name=h.really_unicode(obj.author.name),
            email=h.really_unicode(obj.author.email),
            date=datetime.utcfromtimestamp(obj.authored_date))
        ci.message = h.really_unicode(obj.message or '')

        # diffs
        ci.parent_ids = []
        ci.diffs.added = []
        ci.diffs.removed = []
        ci.diffs.changed = []
        ci.diffs.copied = []

        if obj.parents:
            for parent in obj.parents:
                ci.parent_ids.append(parent.hexsha)

                for diff in parent.diff(obj):
                    if diff.deleted_file:
                        ci.diffs.removed.append(
                            h.really_unicode('/' + diff.a_blob.path))
                    elif diff.new_file:
                        ci.diffs.added.append(
                            h.really_unicode('/' + diff.b_blob.path))
                    elif diff.renamed:
                        ci.diffs.copied.append({
                            'old': h.really_unicode('/' + diff.a_blob.path),
                            'new': h.really_unicode('/' + diff.b_blob.path)
                        })
                    else:
                        ci.diffs.changed.append(
                            h.really_unicode('/' + diff.b_blob.path))
        else:
            ci.diffs.added = [('/' + o.path) for o in
                              obj.tree.traverse(lambda o, z: o.type == 'blob')]

    def add_object_and_commit(self, branch, path):  # pragma no cover
        """
        Add object to git head and make a new commit

        @param path: str    path to object (file or dir)

        """
        subprocess.call([GIT_ADD_SCRIPT, ])

    def _setup_hooks(self):
        """Set up the git post-commit hook"""
        base_url = tg.config.get(
            'cloud_url', tg.config.get('base_url', 'http://localhost:8080'))

        text = self.post_receive_template.substitute(
            url=base_url + '/auth/refresh_repo' + self.url()
        )
        fn = os.path.join(self.fs_path, self.name, 'hooks', 'post-receive')
        with open(fn, 'w') as fp:
            fp.write(text)
        os.chmod(fn, 0755)

    def merge_requests_by_statuses(self, *statuses):  # pragma no cover
        return MergeRequest.query.find({
            'app_config_id': self.app.config._id,
            'status': {'$in': statuses}
        }).sort('request_number')

    def pending_upstream_merges(self):  # pragma no cover
        q = {
            'downstream.project_id': self.project_id,
            'downstream.mount_point': self.app.config.options.mount_point,
            'status': 'open'}
        with self.push_upstream_context():
            return MergeRequest.query.find(q).count()


class GitContentMixin(object):
    repo = None
    commit = None
    path = None

    @LazyProperty
    def _obj(self):
        return self.commit.get_obj_from_path(self.path)

    @property
    def object_id(self):
        return self._obj.hexsha

    @property
    def version_id(self):
        return self.object_id

    @cache_str(name='{args[0].cache_name}', key='last_ci_oid')
    def last_commit_oid(self):
        oid = None
        try:
            oid = self.repo.git_repo.git.rev_list(
                '-1', self.commit.object_id, '--', self.path[1:])
        except git.GitCommandError:  # pragma no cover
            pass
        return oid

    def get_last_commit(self):
        oid = self.last_commit_oid()
        if oid:
            return GitCommit.query.get(
                object_id=oid, repository_id=self.repo._id)

    def prev_commit_oid(self):
        oid = None
        try:
            oids = self.repo.git_repo.git.rev_list(
                '-2', self.commit.object_id,
                '--', self.path[1:].encode('utf8')).split('\n')
        except git.GitCommandError:  # pragma no cover
            pass
        else:
            if len(oids) > 1:
                oid = oids[1]
        return oid

    @LazyProperty
    def prev_commit(self):
        """
        Last commit for this object at which it's contents were different
        from current

        """
        oid = self.prev_commit_oid()
        if oid:
            return GitCommit.query.get(
                object_id=oid, repository_id=self.repo._id)

    def get_timestamp(self):
        """return POSIX timestamp of last modified time"""
        ci = self.get_last_commit()
        if ci:
            dt = ci.committed["date"]
            return time.mktime(dt.timetuple())


class GitFolder(RepositoryFolder, GitContentMixin):

    def __iter__(self):
        for obj in self._obj.traverse(depth=1):
            yield make_content_object(obj, self.commit)

    def ls_commits(self, include_self=False, paths=None):
        """
        Get info dics for the last commit pertaining to each file/folder
        in this tree.

        """
        data = {}
        commits = {}
        if paths is None:
            objs = chain([self], iter(self)) if include_self else iter(self)
        else:
            objs = ifilter(None, (self[path] for path in paths))
            if include_self:
                objs = chain([self], objs)
        for obj in objs:
            ci_oid = obj.last_commit_oid()
            if ci_oid in commits:
                lc = commits[ci_oid]
            else:
                ci = GitCommit.query.get(
                    object_id=ci_oid, repository_id=self.repo._id)
                ci.set_context(self.repo)
                lc = commits[ci_oid] = ci.info()
            data[obj.path] = lc
        return data


class GitFile(RepositoryFile, GitContentMixin):
    folder_cls = GitFolder

    @LazyProperty
    def size(self):
        return self._obj.size

    def open(self):
        return _OpenedGitBlob(self._obj.data_stream)

    def read(self):
        return self.open().read()

    def get_content_hash(self):
        return self.object_id


class _OpenedGitBlob(object):
    CHUNK_SIZE = 4096

    def __init__(self, stream):
        self._stream = stream

    def read(self):
        return self._stream.read()

    def __iter__(self):
        """
        Yields one line at a time, reading from the stream
        """
        buffer = ''
        while True:
            # Replenish buffer until we have a line break
            while '\n' not in buffer:
                chars = self._stream.read(self.CHUNK_SIZE)
                if not chars:
                    break
                buffer += chars
            if not buffer:
                break
            eol = buffer.find('\n')
            if eol == -1:
                # end without \n
                yield buffer
                break
            yield buffer[:eol + 1]
            buffer = buffer[eol + 1:]

    def close(self):
        pass


class MergeRequest(VersionedArtifact):  # pragma no cover
    statuses = ['open', 'merged', 'rejected']

    class __mongometa__:
        name = 'merge-request'
        indexes = ['commit_id']
        unique_indexes = [('app_config_id', 'request_number')]

    type_s = 'Repository'

    request_number = FieldProperty(int)
    status = FieldProperty(str, if_missing='open')
    downstream = FieldProperty(dict(
        project_id=S.ObjectId,
        mount_point=str,
        commit_id=str))
    target_branch = FieldProperty(str)
    creator_id = FieldProperty(S.ObjectId, if_missing=lambda: c.user._id)
    created = FieldProperty(datetime, if_missing=datetime.utcnow)
    summary = FieldProperty(str)
    description = FieldProperty(str)

    @LazyProperty
    def creator(self):
        return User.query.get(_id=self.creator_id)

    @LazyProperty
    def creator_name(self):
        return self.creator.get_pref('display_name') or self.creator.username

    @LazyProperty
    def creator_url(self):
        return self.creator.url()

    @LazyProperty
    def downstream_url(self):
        with self.push_downstream_context():
            return c.app.url

    @LazyProperty
    def downstream_repo_url(self):
        with self.push_downstream_context():
            return c.app.repo.clone_url(
                category='ro',
                username=c.user.username)

    def push_downstream_context(self):
        return g.context_manager.push(
            self.downstream.project_id, self.downstream.mount_point)

    @LazyProperty
    def commits(self):
        return self._commits()

    def _commits(self):
        # FIXME
        result = []
        next = [self.downstream.commit_id]
        while next:
            oid = next.pop(0)
            ci = GitCommit.query.get(object_id=oid)
            if self.app.repo._id == ci.repository_id:
                continue
            result.append(ci)
            next += ci.parent_ids
        with self.push_downstream_context():
            for ci in result:
                ci.set_context(c.app.repo)
        return result

    @classmethod
    def upsert(cls, **kw):
        num = cls.query.find(dict(
            app_config_id=c.app.config._id)).count() + 1
        while True:
            try:
                r = cls(request_number=num, **kw)
                session(cls).flush(r)
                return r
            except pymongo.errors.DuplicateKeyError:  # pragma no cover
                session(cls).expunge(r)
                num += 1

    def url(self):
        return self.app.url + 'merge_requests/%s/' % self.request_number
