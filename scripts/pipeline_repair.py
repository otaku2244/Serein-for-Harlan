"""Resolve a needs_repair batch through the product's own rebuild channel.

The dashboard offers the same two choices by hand: re-validate to keep the
recorded route history, or explicitly void the plan and route again. This
script takes the second one for every batch that is currently stuck, which is
the only self-healing action available -- retrying a stuck plan replays the
same frozen input and fails identically.

Nothing published is lost. pipeline_recovery.rebuild supersedes the old plan
(deleting its route cache and its provenance together), keeps the originals,
the old jobs and the saved Events, and writes one replacement batch with
ignore_route_cache so it cannot rediscover the same broken cache.

Run it inside the memory container, where the database is /data/serein.db.
"""
import argparse
import asyncio
import json
from pathlib import Path
import sqlite3
import sys


def report(conn, title):
    print('=== %s ===' % title)
    for row in conn.execute("SELECT rowid,id,status FROM pipeline_batches "
                            "WHERE status NOT IN ('done','superseded_repair',"
                            "'superseded_input_budget','routed') ORDER BY rowid"):
        print('  #%-4s %-30s %s' % (row['rowid'], row['id'][:30], row['status']))
    for row in conn.execute('SELECT status,count(*) n FROM pipeline_batches GROUP BY status ORDER BY n DESC'):
        print('  %-24s %s' % (row['status'], row['n']))
    print('  unprocessed originals', conn.execute(
        'SELECT count(*) FROM raw_events r WHERE NOT EXISTS '
        '(SELECT 1 FROM raw_processing p WHERE p.raw_id=r.id)').fetchone()[0])
    print()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('database', help='path to serein.db inside the container')
    parser.add_argument('--apply', action='store_true',
                        help='actually rebuild; without it the script only lists stuck batches')
    args = parser.parse_args()
    if not Path(args.database).is_file():
        sys.exit('找不到数据库：%s' % args.database)
    conn = sqlite3.connect('file:%s?mode=ro' % args.database, uri=True)
    conn.row_factory = sqlite3.Row
    stuck = conn.execute("SELECT rowid,id,result_json FROM pipeline_batches "
                         "WHERE status='needs_repair' ORDER BY rowid").fetchall()
    report(conn, 'before')
    if not stuck:
        print('没有 needs_repair 批，无需修复。')
        return
    for row in stuck:
        reason = (json.loads(row['result_json'] or '{}').get('reason') or '?')
        print('待修复 #%s %s\n   reason = %s' % (row['rowid'], row['id'], reason))
    if not args.apply:
        print('[dry-run] 加 --apply 执行。')
        return
    print()
    from serein.extensions import pipeline_recovery
    for row in stuck:
        print('=== rebuild %s ===' % row['id'])
        print(json.dumps(asyncio.run(pipeline_recovery.rebuild(
            args.database, row['id'], 'REBUILD_PIPELINE_BATCH')), ensure_ascii=False, indent=2))
    print()
    conn.close()
    report(sqlite3.connect('file:%s?mode=ro' % args.database, uri=True), 'after')


if __name__ == '__main__':
    main()
