#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
INTERVAL_SECONDS=${1:-5}

case "$INTERVAL_SECONDS" in
    *[!0-9]*|'')
        echo "interval must be a positive integer number of seconds" >&2
        exit 2
        ;;
esac

while :; do
    "$SCRIPT_DIR/sync_from_pi.sh" || true
    sleep "$INTERVAL_SECONDS"
done

