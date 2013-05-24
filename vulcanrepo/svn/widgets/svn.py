import logging

from vulcanforge.auth.model import User
from vulcanforge.cache.decorators import cache_literal

from vulcanrepo.base.widgets import CommitAuthorWidget

LOG = logging.getLogger(__name__)


class SVNCommitAuthor(CommitAuthorWidget):

    @cache_literal(
        '{args[1][author_name]}.avatar', CommitAuthorWidget.cache_key)
    def display(self, value, size=16, **kw):
        user = User.by_username(value['author_name'])
        if user:
            author_content = self.avatar_widget.display(
                user=user, size=size, compact=True)
        else:
            author_content = value['author_name']
        return author_content
