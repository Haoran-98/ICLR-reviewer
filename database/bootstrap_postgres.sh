#!/usr/bin/env bash
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
BASE="${ICLR_DATABASE_HOME:-${ICLR_DATA_DIR:-$REPO/.local-data}/database}"
PREFIX="$BASE/runtime"
PGDATA="$BASE/postgres"
SOCKET="$BASE/run"
LOG="$BASE/postgres.log"
SOURCE="$BASE/vendor"
PORT="${ICLR_DATABASE_PORT:-55432}"
PG_VERSION="16.10"
VECTOR_VERSION="0.8.0"

export PATH="$PREFIX/bin:$PATH"

download() {
  local url="$1" target="$2"
  [ -f "$target" ] || curl --fail --location --retry 5 --output "$target" "$url"
}

build_postgres() {
  [ -x "$PREFIX/bin/postgres" ] && return
  mkdir -p "$SOURCE" "$PREFIX"
  local archive="$SOURCE/postgresql-$PG_VERSION.tar.bz2"
  download "https://ftp.postgresql.org/pub/source/v$PG_VERSION/postgresql-$PG_VERSION.tar.bz2" "$archive"
  rm -rf "$SOURCE/postgresql-$PG_VERSION"
  tar -xjf "$archive" -C "$SOURCE"
  (
    cd "$SOURCE/postgresql-$PG_VERSION"
    ./configure --prefix="$PREFIX" --without-readline --without-zlib --without-icu
    make -j"$(nproc)"
    make install
  )
}

build_pgvector() {
  [ -f "$PREFIX/share/postgresql/extension/vector.control" ] && return
  mkdir -p "$SOURCE"
  local archive="$SOURCE/pgvector-$VECTOR_VERSION.tar.gz"
  download "https://github.com/pgvector/pgvector/archive/refs/tags/v$VECTOR_VERSION.tar.gz" "$archive"
  rm -rf "$SOURCE/pgvector-$VECTOR_VERSION"
  tar -xzf "$archive" -C "$SOURCE"
  make -C "$SOURCE/pgvector-$VECTOR_VERSION" PG_CONFIG="$PREFIX/bin/pg_config" -j"$(nproc)"
  make -C "$SOURCE/pgvector-$VECTOR_VERSION" PG_CONFIG="$PREFIX/bin/pg_config" install
}

initialize() {
  [ -f "$PGDATA/PG_VERSION" ] && return
  mkdir -p "$PGDATA" "$SOCKET"
  "$PREFIX/bin/initdb" --pgdata="$PGDATA" --encoding=UTF8 --locale=C.UTF-8 \
    --auth-local=trust --auth-host=trust
  cat >> "$PGDATA/postgresql.conf" <<EOF
listen_addresses = '127.0.0.1'
port = $PORT
unix_socket_directories = '$SOCKET'
shared_buffers = '1GB'
effective_cache_size = '8GB'
maintenance_work_mem = '512MB'
work_mem = '32MB'
max_wal_size = '4GB'
timezone = 'UTC'
EOF
}

start() {
  mkdir -p "$SOCKET"
  if ! "$PREFIX/bin/pg_ctl" --pgdata="$PGDATA" status >/dev/null 2>&1; then
    "$PREFIX/bin/pg_ctl" --pgdata="$PGDATA" --log="$LOG" start --wait
  fi
}

create_database() {
  local psql=("$PREFIX/bin/psql" -h 127.0.0.1 -p "$PORT")
  "${psql[@]}" postgres -v ON_ERROR_STOP=1 <<'SQL'
SELECT 'CREATE DATABASE iclr_reviewer'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname='iclr_reviewer')\gexec
DO $$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='iclr_owner') THEN CREATE ROLE iclr_owner NOLOGIN; END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='iclr_ingest') THEN CREATE ROLE iclr_ingest NOLOGIN; END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='iclr_app') THEN CREATE ROLE iclr_app NOLOGIN; END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='iclr_readonly') THEN CREATE ROLE iclr_readonly NOLOGIN; END IF;
END $$;
SQL
}

case "${1:-bootstrap}" in
  bootstrap)
    build_postgres
    build_pgvector
    initialize
    start
    create_database
    ;;
  start) start ;;
  stop) "$PREFIX/bin/pg_ctl" --pgdata="$PGDATA" stop --wait ;;
  status) "$PREFIX/bin/pg_ctl" --pgdata="$PGDATA" status ;;
  *) echo "usage: $0 [bootstrap|start|stop|status]" >&2; exit 2 ;;
esac

echo "PostgreSQL: postgresql://$USER@127.0.0.1:$PORT/iclr_reviewer"
