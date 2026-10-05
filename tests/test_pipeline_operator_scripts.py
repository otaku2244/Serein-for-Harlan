"""Operator scripts must never strip route proof from processed messages.

pipeline_routes keeps the routing decision for one raw message;
pipeline_route_provenance keeps the only proof of which batch produced it.
Clearing one without the other produces ownerless cache, which is what made a
frozen batch fail with "cached Track is newer than this frozen batch".

Purely synthetic: a hand-built sqlite file, no production data, no model calls.
"""
import importlib.util
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

SCHEMA = """
CREATE TABLE raw_processing(raw_id INTEGER PRIMARY KEY, outcome TEXT);
CREATE TABLE raw_events(id INTEGER PRIMARY KEY);
CREATE TABLE pipeline_routes(raw_id INTEGER PRIMARY KEY, route_json TEXT);
CREATE TABLE pipeline_route_provenance(raw_id INTEGER PRIMARY KEY, batch_id TEXT, route_json TEXT);
CREATE TABLE fact_events(id INTEGER PRIMARY KEY);
CREATE TABLE documents(id INTEGER PRIMARY KEY, kind TEXT);
CREATE TABLE pipeline_batches(id TEXT, scope TEXT, status TEXT, input_json TEXT);
CREATE TABLE pipeline_jobs(rowid INTEGER, batch_id TEXT);
CREATE TABLE background_state(name TEXT PRIMARY KEY, value_json TEXT);
"""

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
# A message counts as processed whatever its outcome: the settlement itself is
# what stops a message from ever being routed again. Raw 5 is processed and
# fully proved, so it is the case that must survive every clear.
PROCESSED = ((1, 'settled'), (2, 'archived_only'), (3, 'skipped'), (5, 'settled'))
UNPROCESSED = (4,)


def load(name):
    path = SCRIPTS / (name + '.py')
    spec = importlib.util.spec_from_file_location('serein_script_' + name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def database(tmp_path):
    path = tmp_path / 'serein.db'
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    conn.executemany('INSERT INTO raw_processing VALUES (?,?)', PROCESSED)
    conn.executemany('INSERT INTO raw_events VALUES (?)',
                     [(key,) for key in (*[k for k, _ in PROCESSED], *UNPROCESSED)])
    conn.executemany('INSERT INTO pipeline_routes VALUES (?,?)',
                     [(key, 'r%d' % key) for key in range(1, 6)])
    # Raw 4 is the ownerless unsettled row: payload without proof. Raw 5 is
    # processed and proved, so nothing about it may change.
    conn.executemany('INSERT INTO pipeline_route_provenance VALUES (?,?,?)',
                     [(1, 'pipeline:done', 'r1'), (2, 'pipeline:done', 'r2'),
                      (3, 'pipeline:done', 'r3'), (5, 'pipeline:done', 'r5')])
    conn.execute("INSERT INTO fact_events VALUES (1)")
    conn.execute("INSERT INTO documents VALUES (1,'event')")
    conn.executemany('INSERT INTO pipeline_batches VALUES (?,?,?,?)', [
        ('pipeline:done', 's', 'done', '{}'),
        ('pipeline:pending', 's', 'pending', '{}'),
        ('route:routing', 's', 'routing_only', '{}')])
    conn.executemany('INSERT INTO pipeline_jobs VALUES (?,?)',
                     [(1, 'pipeline:done'), (2, 'pipeline:pending'), (3, 'route:routing')])
    conn.execute("INSERT INTO background_state VALUES ('work:pipeline','{}')")
    conn.commit()
    conn.close()
    return path


def rows(path, sql):
    conn = sqlite3.connect(path)
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


def run(name, path, *args):
    # The scripts print Chinese diagnostics, so decode explicitly rather than
    # trusting the console code page of whoever runs the suite.
    return subprocess.run([sys.executable, str(SCRIPTS / (name + '.py')), str(path), *args],
                          capture_output=True, text=True, encoding='utf-8', errors='replace')


def test_orphan_clear_drops_only_unprocessed(tmp_path):
    path = database(tmp_path)
    result = run('pipeline_orphan_cache', path, '--apply')
    assert result.returncode == 0, result.stderr
    # raw_id 4 is the ownerless unsettled row and must go.
    assert [key for key, in rows(path, 'SELECT raw_id FROM pipeline_routes ORDER BY raw_id')] == [1, 2, 3, 5]
    # 5 had no proof to begin with and is processed, so it is left alone.
    assert [key for key, in rows(path, 'SELECT raw_id FROM pipeline_route_provenance ORDER BY raw_id')] == [1, 2, 3, 5]
    assert rows(path, 'SELECT count(*) FROM fact_events')[0][0] == 1


def test_orphan_clear_is_a_no_op_when_every_row_is_proved(tmp_path):
    path = database(tmp_path)
    conn = sqlite3.connect(path)
    # Give raw 4 its producer back: no row is ownerless any more.
    conn.execute("INSERT INTO pipeline_route_provenance VALUES (4,'pipeline:done','r4')")
    conn.commit()
    conn.close()
    result = run('pipeline_orphan_cache', path, '--apply')
    assert result.returncode == 0, result.stderr
    assert '无需清理' in result.stdout
    assert rows(path, 'SELECT count(*) FROM pipeline_routes')[0][0] == 5


def test_orphan_clear_dry_run_touches_nothing(tmp_path):
    path = database(tmp_path)
    before = rows(path, 'SELECT count(*) FROM pipeline_routes')[0][0]
    result = run('pipeline_orphan_cache', path)
    assert result.returncode == 0
    assert 'dry-run' in result.stdout
    assert rows(path, 'SELECT count(*) FROM pipeline_routes')[0][0] == before


def test_reset_clears_proof_and_cache_together(tmp_path):
    path = database(tmp_path)
    result = run('pipeline_reset', path, '--apply')
    assert result.returncode == 0, result.stderr
    kept = [key for key, in rows(path, 'SELECT raw_id FROM pipeline_routes ORDER BY raw_id')]
    proved = [key for key, in rows(path, 'SELECT raw_id FROM pipeline_route_provenance ORDER BY raw_id')]
    # No message may keep a payload while losing its producer, in either direction.
    assert kept == proved == [1, 2, 3, 5]
    assert 4 not in kept and 4 not in proved


def test_reset_keeps_processed_material_and_drops_open_plans(tmp_path):
    path = database(tmp_path)
    assert run('pipeline_reset', path, '--apply').returncode == 0
    assert [key for key, in rows(path, 'SELECT id FROM pipeline_batches')] == ['pipeline:done']
    assert [key for key, in rows(path, 'SELECT rowid FROM pipeline_jobs')] == [1]
    assert rows(path, 'SELECT name FROM background_state') == []
    assert rows(path, 'SELECT count(*) FROM fact_events')[0][0] == 1
    assert rows(path, 'SELECT count(*) FROM documents')[0][0] == 1
    assert rows(path, 'SELECT count(*) FROM raw_processing')[0][0] == len(PROCESSED)
    assert rows(path, 'SELECT count(*) FROM raw_events')[0][0] == 5


def test_reset_dry_run_touches_nothing(tmp_path):
    path = database(tmp_path)
    result = run('pipeline_reset', path)
    assert result.returncode == 0
    assert 'dry-run' in result.stdout
    assert rows(path, 'SELECT count(*) FROM pipeline_batches')[0][0] == 3
    assert rows(path, 'SELECT count(*) FROM pipeline_routes')[0][0] == 5


@pytest.mark.parametrize('name', ['pipeline_orphan_cache', 'pipeline_reset', 'pipeline_repair'])
def test_scripts_report_a_missing_database_without_a_traceback(name, tmp_path):
    result = run(name, tmp_path / 'absent.db')
    assert result.returncode != 0
    assert 'Traceback' not in result.stderr
    # sys.exit() with a message writes it to stderr; an operator must still see
    # why the run stopped instead of a bare non-zero exit.
    assert '找不到数据库' in result.stderr
