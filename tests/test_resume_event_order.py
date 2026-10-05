import pytest
from test_public_features import settings
from serein.application import Application
from serein.core.store import Store
from serein.deployment import save_settings


def bind(store, document_id, source_key, when):
    """Bind one original to an Event with the timestamp that original carries."""
    source_id = store.add_source(source_key, 'source text for ' + source_key)
    store.bind(document_id, source_id, metadata={'created_at': when})


def test_recent_events_follow_when_the_conversation_happened(settings):
    save_settings(settings.database, {'features': {'resume': True}})
    with Store(settings.database) as store:
        # Written out of order on purpose: 'late' gets archived first even
        # though it happened last. A backlog re-run reproduces exactly this.
        store.create('early', 'event', 'Early', 'Early body', created_at='2026-01-03T00:00:00Z')
        store.create('late', 'event', 'Late', 'Late body', created_at='2026-01-01T00:00:00Z')
        store.create('unbound', 'event', 'Unbound', 'Unbound body', created_at='2026-01-02T00:00:00Z')
        bind(store, 'early', 'source-early', '2026-01-01T00:00:00+00:00')
        bind(store, 'late', 'source-late', '2026-01-04T00:00:00+00:00')

    page = Application(settings).contributions.tools['resume']('new')

    # Materials are read oldest first, so the list runs by occurrence time:
    # early (Jan 1), unbound (Jan 2, write time), late (Jan 4). Ordering by
    # write time instead would have put late first, which is the bug.
    assert page['event_ids'] == ['early', 'unbound', 'late']
    # An Event without any binding still has to sort by its write time.
    stamps = {item['id']: item['created_at'] for item in page['items']}
    assert stamps['late'] == '2026-01-04T00:00:00+00:00'
    assert stamps['unbound'] == '2026-01-02T00:00:00Z'


def test_recent_events_ignore_unbound_evidence(settings):
    save_settings(settings.database, {'features': {'resume': True}})
    with Store(settings.database) as store:
        store.create('event', 'event', 'Event', 'Event body', created_at='2026-01-05T00:00:00Z')
        source_id = store.add_source('source', 'retracted text')
        store.bind('event', source_id, metadata={'created_at': '2026-01-09T00:00:00+00:00'})
        store.conn.execute('UPDATE evidence_bindings SET active=0 WHERE source_id=?', (source_id,))

    page = Application(settings).contributions.tools['resume']('new')

    # The only evidence was retracted, so the occurrence time falls back to write time.
    assert page['items'][0]['created_at'] == '2026-01-05T00:00:00Z'