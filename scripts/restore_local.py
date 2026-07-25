"""
scripts/restore_local.py — rebuild a database from a scripts/dump_db.py backup.

    python3 scripts/restore_local.py --backup ~/backups/fairline/<stamp> \
            --target postgresql://fairline@localhost/fairline

Applies schema/001_schema.sql + schema/002_kalshi_ev.sql to the target, loads
every table's rows back, fixes the identity sequences, and verifies the result
against the backup's manifest.

Three things here are less obvious than they look:

1. **TimescaleDB is optional.** The schema declares hypertables, but they are a
   storage-layout choice: partitioning changes where rows live, not what a
   query returns, and converting a hypertable back to a plain table only
   relaxes constraints (Timescale requires unique indexes to include the
   partitioning column; plain Postgres does not). So a research replica without
   the extension returns identical results. If `CREATE EXTENSION timescaledb`
   fails on the target, the Timescale-specific statements are skipped and the
   restore proceeds on plain tables. The one casualty is the `obook_1m`
   continuous aggregate, which belongs to the parked arbitrage subsystem.

2. **Load order is derived, not hardcoded.** Tables are topologically sorted by
   their foreign keys as actually declared in the target catalog, so adding a
   table or an FK later does not silently break this script.

3. **Identity sequences must be advanced by hand.** COPY happily writes
   explicit values into a `GENERATED ALWAYS AS IDENTITY` column, but it does
   not move the underlying sequence -- verified: after restoring rows with ids
   up to 42, the next INSERT still tries id=1 and collides. Every identity
   sequence is therefore reset to its column's max after loading. Skipping this
   leaves a database that reads correctly and fails on the next write.
"""
from __future__ import annotations
import argparse
import gzip
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import psycopg  # noqa: E402

SCHEMA_DIR = os.path.join(os.path.dirname(__file__), "..", "schema")
SCHEMA_FILES = ("001_schema.sql", "002_kalshi_ev.sql")

# Statements that only mean anything with TimescaleDB loaded. Matched against
# whole statements (the schema files contain no dollar-quoting or functions, so
# splitting on ';' is safe -- checked).
TIMESCALE_PATTERNS = (
    re.compile(r"CREATE\s+EXTENSION.*timescaledb", re.I | re.S),
    re.compile(r"create_hypertable\s*\(", re.I | re.S),
    re.compile(r"timescaledb\.continuous", re.I | re.S),
    re.compile(r"add_(continuous_aggregate|retention)_policy\s*\(", re.I | re.S),
)


def _statements(sql: str) -> list[str]:
    return [s.strip() for s in sql.split(";") if s.strip()]


def _apply_schema(conn, *, use_timescale: bool) -> tuple[int, int]:
    applied = skipped = 0
    for fname in SCHEMA_FILES:
        with open(os.path.join(SCHEMA_DIR, fname)) as fh:
            for stmt in _statements(fh.read()):
                if not use_timescale and any(p.search(stmt) for p in TIMESCALE_PATTERNS):
                    skipped += 1
                    continue
                conn.execute(stmt)
                applied += 1
    return applied, skipped


def _load_order(conn, tables: set[str]) -> list[str]:
    """Topological sort on the target's declared foreign keys."""
    deps: dict[str, set[str]] = {t: set() for t in tables}
    for child, parent in conn.execute(
            """
            SELECT c.conrelid::regclass::text, c.confrelid::regclass::text
            FROM pg_constraint c
            JOIN pg_namespace n ON n.oid = c.connamespace
            WHERE c.contype = 'f' AND n.nspname = 'public'
            """).fetchall():
        child, parent = child.split(".")[-1].strip('"'), parent.split(".")[-1].strip('"')
        if child in deps and parent in tables and child != parent:
            deps[child].add(parent)

    ordered: list[str] = []
    while deps:
        ready = sorted(t for t, d in deps.items() if not (d - set(ordered)))
        if not ready:          # a cycle: fall back to alphabetical for the rest
            ready = sorted(deps)
        for t in ready:
            ordered.append(t)
            deps.pop(t)
    return ordered


def _fix_identity_sequences(conn) -> int:
    fixed = 0
    for table, column in conn.execute(
            """
            SELECT c.relname, a.attname
            FROM pg_attribute a
            JOIN pg_class c ON c.oid = a.attrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public' AND a.attidentity IN ('a', 'd')
              AND NOT a.attisdropped
            """).fetchall():
        seq = conn.execute(
            "SELECT pg_get_serial_sequence(%s, %s)", (f"public.{table}", column)
        ).fetchone()[0]
        if not seq:
            continue
        mx = conn.execute(f'SELECT max("{column}") FROM public."{table}"').fetchone()[0]
        if mx is not None:
            conn.execute("SELECT setval(%s, %s, true)", (seq, mx))
            fixed += 1
    return fixed


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Restore a dump_db.py backup.")
    ap.add_argument("--backup", required=True, help="backup directory (with manifest.json)")
    ap.add_argument("--target", default=os.environ.get("TARGET_DATABASE_URL"),
                    help="target DSN (default $TARGET_DATABASE_URL)")
    args = ap.parse_args(argv)

    if not args.target:
        print("no target: pass --target or set $TARGET_DATABASE_URL", file=sys.stderr)
        return 1
    manifest_path = os.path.join(args.backup, "manifest.json")
    if not os.path.exists(manifest_path):
        print(f"no manifest.json in {args.backup}", file=sys.stderr)
        return 1
    manifest = json.load(open(manifest_path))

    try:
        conn = psycopg.connect(args.target, autocommit=True)
        conn.execute("SELECT 1")
    except Exception as e:
        print(f"could not reach target: {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    print(f"backup taken {manifest['created_utc']} from server "
          f"{manifest['server_version']}")
    print(f"target server {conn.execute('show server_version').fetchone()[0]}")

    try:
        conn.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")
        use_timescale = True
    except Exception as e:
        conn.execute("ROLLBACK") if conn.info.transaction_status else None
        use_timescale = False
        print(f"timescaledb unavailable ({type(e).__name__}) -- restoring onto "
              f"plain tables; query results are unaffected (see module docstring)")

    applied, skipped = _apply_schema(conn, use_timescale=use_timescale)
    print(f"schema: {applied} statement(s) applied, {skipped} Timescale-only skipped")

    by_name = {t["table"]: t for t in manifest["tables"]}
    present = {t for t in by_name
               if os.path.exists(os.path.join(args.backup, f"{t}.csv.gz"))}
    failures = []
    for table in _load_order(conn, present):
        path = os.path.join(args.backup, f"{table}.csv.gz")
        with gzip.open(path, "rb") as fh, conn.cursor().copy(
                f'COPY public."{table}" FROM STDIN WITH (FORMAT csv, HEADER true)'
        ) as copy:
            while chunk := fh.read(1 << 16):
                copy.write(chunk)
        n = conn.execute(f'SELECT count(*) FROM public."{table}"').fetchone()[0]
        want = by_name[table]["rows"]
        fp = conn.execute(
            f'SELECT md5(string_agg(h, \'\' ORDER BY h)) FROM '
            f'(SELECT md5(t.*::text) AS h FROM public."{table}" t) s').fetchone()[0]
        want_fp = by_name[table].get("fingerprint")
        ok = n == want and (want_fp is None or fp == want_fp)
        if not ok:
            failures.append(table)
        print(f"  {table:<28} {n:>8}/{want:<8} rows  "
              f"{'OK' if ok else 'MISMATCH'}")

    fixed = _fix_identity_sequences(conn)
    print(f"identity sequences advanced: {fixed}")

    conn.close()
    if failures:
        print(f"\nFAILED: {len(failures)} table(s) did not match the manifest: "
              f"{', '.join(failures)}", file=sys.stderr)
        return 1
    print("\nrestore verified against manifest (row counts + content fingerprints)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
