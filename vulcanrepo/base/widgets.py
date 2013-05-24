import ew as ew_core
import cgi

from pylons import app_globals as g
from jinja2.utils import Markup

from vulcanforge.common.widgets.util import PageList, PageSize
from vulcanforge.resources.widgets import JSLink, CSSLink
from vulcanforge.auth.model import User
from vulcanforge.auth.widgets import Avatar

TEMPLATE_DIR = 'jinja:vulcanrepo.base:templates/widgets/'


class SCMLogWidget(ew_core.Widget):
    template = TEMPLATE_DIR + 'log.html'
    defaults = dict(
        ew_core.Widget.defaults,
        value=None,
        limit=None,
        page=0,
        count=0,
        path='/'
    )

    class fields(ew_core.NameList):
        page_list = PageList()
        page_size = PageSize()

    def resources(self):
        for f in self.fields:
            for r in f.resources():
                yield r


class SCMRevisionWidget(ew_core.Widget):
    template = TEMPLATE_DIR + 'revision.html'
    defaults = dict(
        ew_core.Widget.defaults,
        value=None,
        prev=ew_core.NoDefault,
        next=ew_core.NoDefault)


class SCMCommitWidget(ew_core.Widget):
    template = TEMPLATE_DIR + 'commit.html'
    defaults = dict(ew_core.Widget.defaults, commit=None)
    widgets = dict(revision_widget=SCMRevisionWidget())

    def prepare_context(self, context):
        c = super(SCMCommitWidget, self).prepare_context(context)
        c.update(self.widgets)
        return c


class CommitAuthorWidget(ew_core.Widget):
    avatar_widget = Avatar()
    cache_name = '{email}.avatar'

    @staticmethod
    def cache_key(kwargs={}, *args, **kw):
        return 'commitauthor{size}'.format(size=kwargs.get('size', 16))

    def display(self, value, size=16, load_user=False, **kw):
        """
        :param value: commit_info
        :param kw:
        :return: html

        """
        author_content = ''
        if value.get('author_email'):
            if g.cache:
                cache_key = self.cache_key(kwargs={'size': size})
                cache_name = self.cache_name.format(
                    email=value['author_email'])
                author_content = g.cache.hget(cache_name, cache_key)
                if author_content:
                    return Markup(author_content)

            if load_user:
                user = User.by_email_address(value['author_email'])
                if user:
                    author_content = self.avatar_widget.display(
                        user=user, size=size, compact=True)
            if not author_content:
                author_content = (
                    '<img class="emboss x{size}" src="{src}" '
                    'alt="{author}" title="{author}" />').format(
                    src=g.gravatar(value['author_email'], size=size),
                    author=cgi.escape(value['author_name']),
                    size=size
                )

            if load_user and g.cache:
                g.cache.hset(cache_name, cache_key, author_content)
        elif value.get('author_name'):
            author_content = cgi.escape(value['author_name'])
        return Markup(author_content)


class SCMCommitBrowserWidget(ew_core.Widget):
    template = TEMPLATE_DIR + 'commit_browser.html'
    defaults = dict(
        ew_core.Widget.defaults,
        built_tree=None,
        max_row=0,
        next_column=0)

    def resources(self):
        yield JSLink('repo/commit_browser.js')
        yield CSSLink('repo/commit_browser.css')
