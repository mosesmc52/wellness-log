#!/bin/sh
set -eu

if [ "${SKIP_DB_BOOTSTRAP:-0}" != "1" ]; then
  database_path="${SPACES_DB_PATH:-/app/data/wellness.db}"

  if [ ! -s "${database_path}" ]; then
    configured=0
    missing=""
    for variable_name in SPACES_KEY SPACES_SECRET SPACES_BUCKET; do
      eval "variable_value=\${${variable_name}:-}"
      if [ -n "${variable_value}" ]; then
        configured=1
      else
        missing="${missing} ${variable_name}"
      fi
    done

    if [ -z "${missing}" ]; then
      echo "Local SQLite database is missing; downloading it from DigitalOcean Spaces."
      python /app/spaces_sqlite_sync.py download --no-overwrite-local --allow-missing
    elif [ "${configured}" = "1" ]; then
      echo "Spaces is partially configured; missing:${missing}" >&2
      exit 1
    else
      echo "Local SQLite database is missing and Spaces is not configured; starting with a new database."
    fi
  fi
fi

exec "$@"
