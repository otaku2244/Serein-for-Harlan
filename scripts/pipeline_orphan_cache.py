"""Report and clear ownerless route cache left behind by a partial pipeline reset.

pipeline_routes holds the routing decision for one raw message;
pipeline_route_provenance holds the only proof of WHICH batch produced it.
Clear one without the other and the cache becomes ownerless: a later batch
reuses the row, cannot prove who routed it, falls back to the live Track card
in pipeline_tracks, and that card has already moved past the frozen batch's
upper bound -- "cached Track is newer than this frozen batch" -> needs_repair.

Only unsettled messages are cleared. A message counts as settled as soon as any
raw_processing row exists -- the outcome may be settled, archived_only or
skipped -- because settled routes must stay: load_tracks() reads pipeline_routes
to find which Tracks have proven recent activity. Their missing provenance is
harmless, they can never be queried again.
"""
import argparse
from pathlib import Path
import sqlite3
import sys

ORPHAN = 'raw_id NOT IN (SELECT raw_id FROM pipeline_route_provenance)'
SETTLED = 'raw_id IN (SELECT raw_id FROM raw_processing)'


def connect(path):
    if not Path(path).is_file():
        sys.exit('找不到数据库：%s' % path)
    return sqlite3.connect(path, timeout=30, isolation_level=None)


def survey(conn):
    one = lambda sql: conn.execute(sql).fetchone()[0]
    return {
        'routes': one('SELECT count(*) FROM pipeline_routes'),
        'provenance': one('SELECT count(*) FROM pipeline_route_provenance'),
        'orphan_total': one('SELECT count(*) FROM pipeline_routes WHERE ' + ORPHAN),
        'orphan_unsettled': one('SELECT count(*) FROM pipeline_routes WHERE %s AND NOT(%s)' % (ORPHAN, SETTLED)),
        'orphan_settled': one('SELECT count(*) FROM pipeline_routes WHERE %s AND %s' % (ORPHAN, SETTLED)),
        'events': one('SELECT count(*) FROM fact_events'),
        'processed': one('SELECT count(*) FROM raw_processing'),
        'unsettled': one('SELECT count(*) FROM raw_events r WHERE NOT EXISTS '
                         '(SELECT 1 FROM raw_processing p WHERE p.raw_id=r.id)'),
        'open_batches': one("SELECT count(*) FROM pipeline_batches "
                            "WHERE status IN ('pending','needs_repair')"),
    }


def show(conn, title):
    print('=== %s ===' % title)
    for key, value in survey(conn).items():
        print('  %-20s %s' % (key, value))
    print()


def clear_unsettled(conn):
    """Both tables are cleared together, so no row can lose its proof."""
    conn.execute('BEGIN IMMEDIATE')
    try:
        deleted = conn.execute(
            'DELETE FROM pipeline_routes WHERE %s AND NOT(%s)' % (ORPHAN, SETTLED)).rowcount
        conn.execute('COMMIT')
    except Exception:
        conn.execute('ROLLBACK')
        raise
    return deleted


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('database', help='path to serein.db')
    parser.add_argument('--apply', action='store_true',
                        help='actually delete; without it the script only reports')
    args = parser.parse_args()
    conn = connect(args.database)
    try:
        show(conn, 'before')
        if not survey(conn)['orphan_unsettled']:
            print('没有未结算的孤儿缓存，无需清理。')
            return
        if not args.apply:
            print('[dry-run] 加 --apply 执行。')
            return
        print('已删除未结算孤儿缓存 %d 行。' % clear_unsettled(conn))
        print()
        show(conn, 'after')
        remaining = survey(conn)['orphan_unsettled']
        print('校验：剩余未结算孤儿 = %d %s' % (remaining, 'OK' if remaining == 0 else '异常'))
    finally:
        conn.close()


if __name__ == '__main__':
    main()
