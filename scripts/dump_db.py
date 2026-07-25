"""
scripts/dump_db.py — data-only backup of the configured database to gzipped CSV.

    python3 scripts/dump_db.py                      # -> ~/backups/fairline/<utc-stamp>/
    python3 scripts/dump_db.py --out /some/dir

Why this exists rather than `pg_dump`: pg_dump refuses to dump a server newer
than itself, and the client shipped with Ubuntu 22.04 is 14.x while the hosted
database is 18.x. This uses server-side COPY over the ordinary psycopg
connection, which has no such version coupling. (Once postgresql-client-18 is
installed, pg_dump is the better tool for a full logical dump — this script
stays useful as the version-agnostic fallback and as the thing that writes the
integrity fingerprints restore_local.py checks.)

Data-only on purpose: the DDL is versioned in schema/001_schema.sql and
schema/002_kalshi_ev.sql. The rows are the part that cannot be rebuilt --
Kalshi serves nested market data for only ~68 rolling days per series, so the
early end of any capture slides permanently out of reach of the API.

Writes per table: <table>.csv.gz, plus a manifest.json recording row counts and
an order-independent content fingerprint for each (see _fingerprint).
"""
from __future__ import annotations
import argparse
import gzip
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import store  # noqa: E402

DEFAULT_OUT = os.path.expanduser("~/backups/fairline")


def _fingerprint(conn, table: str) -> str | None:
    """An order-independent digest of a table's contents.

    A checksum of the raw COPY stream would be worthless here: `SELECT *` has
    no guaranteed row order, so the same data can serialise two ways and a
    byte-for-byte comparison would report spurious corruption. Hashing each row
    and aggregating in sorted order removes that dependence, so this value is
    comparable between the source and a restored copy. NULL/None for an empty
    table."""
    return conn.execute(
        f'SELECT md5(string_agg(h, \'\' ORDER BY h)) FROM '
        f'(SELECT md5(t.*::text) AS h FROM public."{table}" t) s').fetchone()[0]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Data-only CSV backup of $DATABASE_URL.")
    ap.add_argument("--out", default=DEFAULT_OUT,
                    help=f"backup root directory (default {DEFAULT_OUT})")
    args = ap.parse_args(argv)

    try:
        conn = store.connect()
        conn.execute("SELECT 1")
    except Exception as e:
        print(f"could not reach Postgres via $DATABASE_URL (see README -> "
              f"'Database setup'): {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = os.path.join(args.out, stamp)
    os.makedirs(dest, exist_ok=True)

    # Ordinary user tables only. TimescaleDB's internal chunk and catalog
    # schemas are excluded deliberately: they are rebuilt from the hypertable
    # definitions when the schema is reapplied, and copying them into a target
    # without the extension would fail outright.
    tables = [r[0] for r in conn.execute(
        "SELECT tablename FROM pg_tables WHERE schemaname = 'public' "
        "ORDER BY tablename").fetchall()]

    manifest = {
        "created_utc": stamp,
        "server_version": conn.execute("show server_version").fetchone()[0],
        "tables": [],
    }
    total = 0
    for t in tables:
        n = conn.execute(f'SELECT count(*) FROM public."{t}"').fetchone()[0]
        path = os.path.join(dest, f"{t}.csv.gz")
        with gzip.open(path, "wb") as fh:
            with conn.cursor().copy(
                    f'COPY (SELECT * FROM public."{t}") TO STDOUT '
                    f'WITH (FORMAT csv, HEADER true)') as copy:
                for chunk in copy:
                    fh.write(bytes(chunk))
        manifest["tables"].append({
            "table": t, "rows": n,
            "bytes_gz": os.path.getsize(path),
            "fingerprint": _fingerprint(conn, t),
        })
        total += n
        print(f"  {t:<28} {n:>8} rows  {os.path.getsize(path)/1024:>9.1f} KiB gz",
              flush=True)

    with open(os.path.join(dest, "manifest.json"), "w") as fh:
        json.dump(manifest, fh, indent=2)
    print(f"\nbackup: {dest}\n{len(tables)} table(s), {total} row(s)")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
