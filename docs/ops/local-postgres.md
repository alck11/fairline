# Local Postgres for backtesting and calibration research

A local replica for research. Neon stays as the hosted database; this is where
the study and backtest loops run, because they are latency-bound, not
throughput-bound: a full calibration pass issues tens of thousands of small
queries, and at a ~30ms round trip to Neon that is half an hour of waiting
regardless of how cheap the queries are. Over a Unix socket the same work is
seconds.

Cost is *not* the reason (Neon's Launch plan is usage-based, and a full pass
costs a few cents). Iteration speed is.

## Use PostgreSQL 18, not 14

**Confirmed 2026-07-25:** the Neon server is `18.4`, and PGDG's jammy
repository offers `postgresql-18` at `18.4-1.pgdg22.04+1` — the same
major.minor. Matching versions means the research replica cannot disagree with
production over planner or type behaviour, and it makes `pg_dump`/`pg_restore`
work against Neon (the Ubuntu-default client 14 refuses a newer server
outright, which is why `scripts/dump_db.py` exists).

Only `postgresql-client-14` is currently installed here — there is no local
server, no `initdb`, and no cluster tooling, so nothing is lost by going to 18.

## 1. Install (needs sudo)

```bash
sudo apt install -y curl ca-certificates
sudo install -d /usr/share/postgresql-common/pgdg
sudo curl -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
     --fail https://www.postgresql.org/media/keys/ACCC4CF8.asc
. /etc/os-release
echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] \
https://apt.postgresql.org/pub/repos/apt $VERSION_CODENAME-pgdg main" \
  | sudo tee /etc/apt/sources.list.d/pgdg.list
sudo apt update
sudo apt install -y postgresql-18 postgresql-client-18
```

On WSL2 there is no systemd by default, so start the cluster directly:

```bash
sudo pg_ctlcluster 18 main start
pg_isready          # expect: /var/run/postgresql:5432 - accepting connections
```

(Add that `start` line to your shell profile if you want it up on every shell.)

## 2. Create the database and role

```bash
sudo -u postgres createuser --superuser "$USER"
sudo -u postgres createdb -O "$USER" fairline
psql -d fairline -c 'select version()'
```

Superuser is deliberate for a local research box: `restore_local.py` creates
extensions and resets identity sequences.

## 3. Restore the latest backup

```bash
cd ~/projects/fairline
python3 scripts/restore_local.py \
    --backup "$(ls -d ~/backups/fairline/*/ | tail -1)" \
    --target "postgresql:///fairline"
```

It applies `schema/001` + `schema/002`, loads every table in foreign-key
order, advances the identity sequences, and verifies row counts **and**
per-table content fingerprints against the backup manifest. It prints
`MISMATCH` per table and exits non-zero if anything fails to match — a silent
partial restore is the one outcome worth engineering against.

### TimescaleDB is not required

The schema declares hypertables, but PGDG does not ship TimescaleDB (it lives
in Timescale's own repository, whose PG18 support you would need to check). The
restore detects this and skips the Timescale-only statements.

This is safe: hypertables are a *storage layout*. Partitioning changes where
rows live, not what a query returns, and going hypertable→plain only relaxes
constraints (Timescale requires unique indexes to include the partitioning
column; plain Postgres does not). Study and backtest results are unchanged. The
one thing you lose is the `obook_1m` continuous aggregate, which belongs to the
parked arbitrage subsystem and is untouched by WP-6/WP-7.

Install TimescaleDB later if the arb track is revived; the restore will pick it
up automatically.

## 4. Point the tools at it

```bash
export DATABASE_URL="postgresql:///fairline"
python3 src/run_calibration.py --start 2026-05-17 --end 2026-07-26 --step-hours 6
```

To switch back to Neon, read the DSN out of `.env` **quoted**:

```bash
export DATABASE_URL="$(grep -m1 '^DATABASE_URL=' .env | cut -d= -f2-)"
```

Do not use `source .env` for this. Neon connection strings contain `&`, which
bash parses as a background-job operator: the variable silently fails to
export, *and* the full DSN including the password gets echoed to the terminal
in a job-control message. That happened during this project's setup.

## Backups

```bash
python3 scripts/dump_db.py            # -> ~/backups/fairline/<utc-stamp>/
```

Worth doing on a schedule against whichever database is authoritative. Kalshi
serves nested market data for only ~68 rolling days per series, so the early
end of any capture is **permanently** unrecoverable once it ages out — the
2026-05-17 start of the current KXHIGHNY window cannot be re-fetched from the
API today. Roughly 500 KiB gzipped for the whole database at present, so there
is no reason to be sparing.

## A note on the pooled endpoint

Neon hands out a `-pooler` hostname by default. Do not use it for this project:
PgBouncer's transaction pooling drops the session `search_path`, so every
unqualified table name in `store.py` fails with `UndefinedTable` while the data
sits there intact. Strip `-pooler.` from the host for a direct connection —
also the right choice for long-running batch work, which is what every entry
point here does.
