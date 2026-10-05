"""Domain policy must reach the client so Event labels stop claiming auto-surfacing.

A restricted domain is rejected during recall before the stored manual_surface
column is consulted, so a label built from manual_surface alone reports a stale
"可自动浮现" for every Event the operator has already restricted.
"""
import json

import pytest
from fastapi.testclient import TestClient

from serein.api.http import create_app
from serein.compat.events import Events
from serein.config import Settings
from serein.core import Store
from serein.deployment import save_settings
from serein.recall.index import build_index
from test_live_events import item


@pytest.fixture
def live(tmp_path):
    settings = Settings(tmp_path / 'serein.db', tmp_path / 'index.sqlite', writable=True)
    with Store(settings.database):
        pass
    Events(settings.database, initialize=True)
    build_index(settings.database, settings.index)
    with TestClient(create_app(settings, token='test', live=True),
                   headers={'Authorization': 'Bearer test'}) as client:
        yield settings, client


def _settle(client):
    body = {'operation_id': 'domain_batch', 'items': [item()]}
    response = client.post('/api/fact-events/settlement', json=body)
    assert response.status_code == 200, response.text
    return response.json()['items'][0]['item_id']


def _list(client):
    response = client.get('/api/fact-events?type=event&status=active&include_sources=1'
                           '&limit=500&offset=0')
    assert response.status_code == 200, response.text
    return response.json()['items']


def _publish_policies(database, policy):
    save_settings(database, {'tagging': {'policies': {'event': policy}}})


def test_list_reports_domain_and_policy_per_event(live):
    settings, client = live
    key = _settle(client)
    row = next(item for item in _list(client) if item['item_id'] == key)
    assert row['domain_policy'] == 'normal', 'an unconfigured domain defaults to normal'
    assert 'canonical_domain' in row, 'the client needs the domain to label the rule'


def test_restricted_domain_is_reported_even_when_manual_surface_allows(live):
    settings, client = live
    key = _settle(client)
    domain = next(item for item in _list(client)
                  if item['item_id'] == key)['canonical_domain']

    _publish_policies(settings.database, {domain: 'explicit_only'})
    row = next(item for item in _list(client) if item['item_id'] == key)

    assert row['recallable'] is True, 'the stored verdict is untouched by the rule'
    assert row['domain_policy'] == 'explicit_only', \
        'the client must see the rule that recall actually applies first'


def test_excluded_domain_is_distinguished_from_explicit_only(live):
    settings, client = live
    key = _settle(client)
    domain = next(item for item in _list(client)
                  if item['item_id'] == key)['canonical_domain']

    _publish_policies(settings.database, {domain: 'excluded'})
    row = next(item for item in _list(client) if item['item_id'] == key)

    assert row['domain_policy'] == 'excluded'
    assert row['domain_policy'] != 'explicit_only', \
        'excluded blocks injection outright and must not read as a soft restriction'


def test_policy_is_scoped_to_the_published_kind(live):
    settings, client = live
    key = _settle(client)
    domain = next(item for item in _list(client)
                  if item['item_id'] == key)['canonical_domain']

    _publish_policies(settings.database, {domain: 'excluded'})
    assert next(item for item in _list(client)
                if item['item_id'] == key)['domain_policy'] == 'excluded'

    _publish_policies(settings.database, {})
    assert next(item for item in _list(client)
                if item['item_id'] == key)['domain_policy'] == 'normal', \
        'clearing the published policy must not leave a stale restriction behind'


def test_global_domain_policy_applies_without_a_per_kind_entry(live):
    """Recall falls back to the flat domain map; the label must agree with it."""
    settings, client = live
    key = _settle(client)
    domain = next(item for item in _list(client)
                  if item['item_id'] == key)['canonical_domain']

    save_settings(settings.database, {
        'tagging': {
            'domains': [{'key': domain, 'label': domain, 'description': '', 'policy': 'excluded'}],
        }
    })
    row = next(item for item in _list(client) if item['item_id'] == key)
    assert row['domain_policy'] == 'excluded', \
        'the flat domains map is what recall falls back to, so it must reach the label too'