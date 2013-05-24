import logging

import ew as ew_core
import ew.jinja2_ew as ew

from vulcanforge.common.widgets.forms import ForgeForm

from vulcanrepo.git.model import MergeRequest
LOG = logging.getLogger(__name__)


class MergeRequestWidget(ForgeForm):
    source_branches = []
    target_branches = []

    @property
    def fields(self):
        result = [
            ew.TextField(name='summary'),
            ew.SingleSelectField(
                name='source_branch',
                label='Source Branch',
                options=self.source_branches),
            ew.SingleSelectField(
                name='target_branch',
                label='Target Branch',
                options=self.target_branches),
            ew.TextArea(name='description')]
        return result


class MergeRequestFilterWidget(ForgeForm):
    defaults = dict(
        ForgeForm.defaults,
        submit_text='Filter',
        method='GET')

    class fields(ew_core.NameList):
        status = ew.MultiSelectField(options=MergeRequest.statuses)


class MergeRequestDisposeWidget(ForgeForm):

    class fields(ew_core.NameList):
        status = ew.SingleSelectField(
            label='Change Status',
            options=MergeRequest.statuses)
