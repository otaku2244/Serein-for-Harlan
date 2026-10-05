"""Discard unfinished pipeline work so unsettled originals are routed again.

Published Events and every processed original are never touched. A processed
original is any row in raw_processing, whatever its outcome (settled,
archived_only or skipped); its route receipts stay so Track continuity holds.
Every step is reversible in the sense that nothing already published is
removed: only pending plans, their jobs, and the route proof of UNPROCESSED
messages go.

The producer must go BEFORE its cache, and both must go together.
pipeline_routes rows that keep a payload while losing their provenance become
ownerless cache: a later batch reuses such a row, cannot prove who routed it,
falls back to the live Track card in pipeline_tracks, and that card has already
moved past the frozen batch's own upper bound -- "cached Track is newer than
this frozen batch" -> needs_repair. Clearing provenance alone creates exactly
that, which is why routes are cleared in the same step and never on their own.

Run it inside the memory container, where the database is /data/serein.db.
Add --apply to execute; without it every step is only counted.
"""
import argparse
from pathlib import Path
import sqlite3
import sys

STEPS = [
    # A message counts as settled as soon as any raw_processing row exists
    # (outcome settled / archived_only / skipped). Those routes keep their
    # payload: load_tracks() reads pipeline_routes to find which Tracks have
    # proven recent activity, so clearing them would cut Track continuity. A
    # missing provenance row on them is harmless -- they can never be queried
    # again, so do not "fix" it by inventing a producer.
    ('route proof of unsettled originals', 'DELETE FROM pipeline_route_provenance '
     'WHERE raw_id NOT IN (SELECT raw_id FROM raw_processing)'),
    ('ownerless cache of unsettled originals', 'DELETE FROM pipeline_routes '
     'WHERE raw_id NOT IN (SELECT raw_id FROM raw_processing)'),
    # route: batches carry a stale runtime_revision; leaving them behind makes
    # the next batch fail with needs_repair for an unrelated-looking reason.
    ('jobs of unfinished pipeline:/route: batches', "DELETE FROM pipeline_jobs "
     "WHERE batch_id IN (SELECT id FROM pipeline_batches "
     "WHERE (id LIKE 'pipeline:%' OR id LIKE 'route:%') AND status!='done')"),
    ('unfinished pipeline:/route: batches', "DELETE FROM pipeline_batches "
     "WHERE (id LIKE 'pipeline:%' OR id LIKE 'route:%') AND status!='done'"),
    ('stale work:pipeline lease and progress', "DELETE FROM background_state "
     "WHERE name LIKE 'work:pipeline%'"),
]

KEEP = """SELECT 'documents(kind=event)', count(*) FROM documents WHERE kind='event'
UNION ALL SELECT 'raw_processing(settled)', count(*) FROM raw_processing WHERE outcome='settled'
UNION ALL SELECT 'raw_processing(archived_only)', count(*) FROM raw_processing WHERE outcome='archived_only'
UNION ALL SELECT 'raw_processing(skipped)', count(*) FROM raw_processing WHERE outcome='skipped'
UNION ALL SELECT 'route rows of settled', count(*) FROM pipeline_routes
            WHERE raw_id IN (SELECT raw_id FROM raw_processing)
UNION ALL SELECT 'unsettled originals', count(*) FROM raw_events r WHERE NOT EXISTS
            (SELECT 1 FROM raw_processing p WHERE p.raw_id=r.id)"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('database', help='path to serein.db inside the container')
    parser.add_argument('--apply', action='store_true',
                        help='actually delete; without it the script only counts')
    args = parser.parse_args()
    if not Path(args.database).is_file():
        sys.exit('找不到数据库：%s' % args.database)
    conn = sqlite3.connect(args.database, timeout=30, isolation_level=None)
    try:
        print('=== 将删除 ===')
        plan = []
        for name, sql in STEPS:
            count = conn.execute(sql.replace('DELETE FROM', 'SELECT count(*) FROM', 1)).fetchone()[0]
            plan.append((name, sql, count))
            print('  %-42s %s 行' % (name, count))
        print()
        print('=== 保留不动 ===')
        for name, count in conn.execute(KEEP):
            print('  %-42s %s 条' % (name, count))
        print()
        if not args.apply:
            print('[dry-run] 加 --apply 执行。')
            return
        conn.execute('BEGIN IMMEDIATE')
        try:
            for _, sql, _ in plan:
                conn.execute(sql)
            conn.execute('COMMIT')
        except Exception:
            conn.execute('ROLLBACK')
            raise
        print('=== 已执行 ===')
        for name, sql, _ in plan:
            left = conn.execute(sql.replace('DELETE FROM', 'SELECT count(*) FROM', 1)).fetchone()[0]
            print('  %-42s 剩余 %s 行' % (name, left))
    finally:
        conn.close()


if __name__ == '__main__':
    main()
