from vulcanforge.common.util.model import pymongo_db_collection
from vulcanforge.common.validators import JSONValidator
from vulcanforge.stats import BaseStatsAggregator, StatsQuerySchema


class CommitQuerySchema(StatsQuerySchema):
    user = JSONValidator()


class CommitAggregator(BaseStatsAggregator):
    timestamp_field = 'authored.date'

    def __init__(self, repo=None, collection=None, **kwargs):
        super(CommitAggregator, self).__init__(**kwargs)
        self.repo = repo
        if self.repo:
            db, self.collection = pymongo_db_collection(repo.commit_cls)
        else:
            self.collection = collection

    def _make_user_query(self, user_spec):
        q = {}
        if 'name' in user_spec:
            q['authored.name'] = user_spec['name']
        if 'email' in self.user:
            q['authored.email'] = user_spec['email']
        return q

    def make_query(self):
        super(CommitAggregator, self).make_query()
        self.query['authored.date'] = {'$ne': None}
        if self.repo:
            self.query['app_config_id'] = self.repo.app_config_id
        # user should be a dictionary (name, email) or list of such dicts
        if self.user:
            if isinstance(self.user, dict):
                self.query.update(self._make_user_query(self.user))
            else:
                self.query['$or'] = [
                    self._make_user_query(u) for u in self.user]

        return self.query

    def make_group_id_spec(self):
        id_spec = super(CommitAggregator, self).make_group_id_spec()
        if 'user' in self.bins:
            id_spec.update({
                'name': '$authored.name',
                'email': '$authored.email'
            })
        if 'repos' in self.bins:
            id_spec['repo'] = '$repository_id'
        return id_spec

    def fix_value(self, key, value, row):
        if self.label == 'name' and key == 'label':
            if row['_id']['email']:
                value += ' <{}>'.format(row['_id']['email'])
            return value
        return super(CommitAggregator, self).fix_value(key, value, row)
