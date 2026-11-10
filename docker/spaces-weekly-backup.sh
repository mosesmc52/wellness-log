#!/bin/sh
set -eu

for variable_name in SPACES_KEY SPACES_SECRET SPACES_BUCKET; do
  eval "variable_value=\${${variable_name}:-}"
  if [ -z "${variable_value}" ]; then
    echo "Weekly Spaces database upload skipped: ${variable_name} is not configured."
    exit 0
  fi
done

cd /app
exec python spaces_sqlite_sync.py upload
