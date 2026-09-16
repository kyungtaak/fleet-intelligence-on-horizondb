#!/bin/sh
set -eu

if [ "${RUN_DATABASE_SETUP:-false}" = "true" ]; then
    python -m app.setup_database
fi

exec python -m app.server