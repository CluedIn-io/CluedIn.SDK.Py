import pytest

from cluedin.rules import (RuleScope, get_all_rule_details, get_all_rules,
                           get_rules_page)
from cluedin.rules import rules as rules_module


def response(rules, total):
    """Builds a get_rules response holding one page."""
    return {
        'data': {
            'management': {
                'id': 'management',
                'rules': {
                    'total': total,
                    'data': rules,
                    '__typename': 'RuleCollection',
                },
                '__typename': 'Management',
            }
        }
    }


def page_of(start, count):
    """Builds `count` rule summaries numbered from `start`."""
    return [{'id': str(i), 'name': f'Rule {i}'} for i in range(start, start + count)]


class FakeServer:
    """
    Stands in for org_gql, serving a fixed set of rules 20 per page, and
    recording the variables of every call.
    """

    def __init__(self, total, page_size=20):
        self.total = total
        self.page_size = page_size
        self.calls = []

    def __call__(self, _context, _query, variables=None):
        variables = variables or {}
        self.calls.append(variables)
        page_number = variables.get('pageNumber', 1)
        start = (page_number - 1) * self.page_size
        if start >= self.total:
            return response([], self.total)
        count = min(self.page_size, self.total - start)
        return response(page_of(start, count), self.total)


@pytest.fixture(name='server')
def server_fixture(monkeypatch):
    """Installs a FakeServer of 46 rules in place of org_gql."""
    fake = FakeServer(total=46)
    monkeypatch.setattr(rules_module, 'org_gql', fake)
    return fake


class TestGetAllRules:
    # pylint: disable=missing-docstring

    def test_walks_every_page(self, server):
        result = list(get_all_rules(None, RuleScope.ENTITY))

        assert len(result) == 46
        assert [r['id'] for r in result] == [str(i) for i in range(46)]

    def test_requests_only_the_pages_it_needs(self, server):
        list(get_all_rules(None, RuleScope.ENTITY))

        # 46 rules at 20 per page is 3 pages, and the total says to stop there
        # rather than asking for an empty 4th.
        assert [call['pageNumber'] for call in server.calls] == [1, 2, 3]

    def test_passes_the_scope(self, server):
        list(get_all_rules(None, RuleScope.SURVIVORSHIP))

        assert server.calls[0]['scope'] == 'Survivorship'

    def test_defaults_to_data_part(self, server):
        list(get_all_rules(None))

        assert server.calls[0]['scope'] == 'DataPart'

    def test_is_lazy(self, server):
        generator = get_all_rules(None, RuleScope.ENTITY)

        next(generator)

        # Taking one rule must not have fetched every page.
        assert len(server.calls) == 1

    def test_single_page(self, monkeypatch):
        monkeypatch.setattr(rules_module, 'org_gql', FakeServer(total=5))

        assert len(list(get_all_rules(None))) == 5

    def test_exactly_one_full_page(self, monkeypatch):
        # The total is reached exactly at a page boundary, so there must be no
        # extra request for an empty page.
        fake = FakeServer(total=20)
        monkeypatch.setattr(rules_module, 'org_gql', fake)

        assert len(list(get_all_rules(None))) == 20
        assert len(fake.calls) == 1

    def test_no_rules(self, monkeypatch):
        monkeypatch.setattr(rules_module, 'org_gql', FakeServer(total=0))

        assert not list(get_all_rules(None))

    def test_forwards_filters(self, server):
        list(get_all_rules(None, RuleScope.ENTITY,
                           search_name='City', is_active=True))

        assert server.calls[0]['searchName'] == 'City'
        assert server.calls[0]['isActive'] is True

    def test_stops_if_the_server_ignores_the_page_number(self, monkeypatch):
        # A server that always serves page 1 would otherwise be paged forever.
        calls = []

        def always_page_one(_context, _query, variables=None):
            calls.append(variables)
            return response(page_of(0, 20), 46)

        monkeypatch.setattr(rules_module, 'org_gql', always_page_one)

        result = list(get_all_rules(None, RuleScope.ENTITY))

        assert len(result) == 20
        assert len(calls) == 2

    def test_stops_at_a_short_page_when_the_total_is_wrong(self, monkeypatch):
        # The total over-reports; the empty page has to end the walk.
        def short(_context, _query, variables=None):
            page_number = (variables or {}).get('pageNumber', 1)
            if page_number == 1:
                return response(page_of(0, 20), 999)
            return response([], 999)

        monkeypatch.setattr(rules_module, 'org_gql', short)

        assert len(list(get_all_rules(None))) == 20

    def test_max_pages_caps_the_walk(self, server):
        result = list(get_all_rules(None, RuleScope.ENTITY, max_pages=2))

        assert len(result) == 40


class TestGetRulesPage:
    # pylint: disable=missing-docstring

    def test_reads_a_page(self):
        page = get_rules_page(response(page_of(0, 2), 2))

        assert page['total'] == 2
        assert len(page['data']) == 2

    def test_raises_on_graphql_errors(self):
        with pytest.raises(ValueError, match='GraphQL query failed'):
            get_rules_page({'errors': [{'message': 'Unauthorized'}]})

    @pytest.mark.parametrize('payload', [
        {},
        {'data': None},
        {'data': {}},
        {'data': {'management': None}},
        {'data': {'management': {}}},
    ])
    def test_raises_when_there_is_no_page(self, payload):
        with pytest.raises(ValueError):
            get_rules_page(payload)


class TestGetAllRuleDetails:
    # pylint: disable=missing-docstring

    def test_fetches_each_rule_in_full(self, monkeypatch):
        fake = FakeServer(total=3)
        detail_calls = []

        def org_gql(context, query, variables=None):
            if 'getRule(' in query or '$id' in query:
                detail_calls.append(variables['id'])
                return {'data': {'management': {'rule': {'id': variables['id']}}}}
            return fake(context, query, variables)

        monkeypatch.setattr(rules_module, 'org_gql', org_gql)

        result = list(get_all_rule_details(None, RuleScope.ENTITY))

        assert detail_calls == ['0', '1', '2']
        assert [r['data']['management']['rule']['id'] for r in result] == \
            ['0', '1', '2']
