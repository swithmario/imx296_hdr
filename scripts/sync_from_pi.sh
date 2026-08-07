#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(dirname -- "$SCRIPT_DIR")

PI_HOST=${RPICAM_HOST:?Set RPICAM_HOST to the Raspberry Pi host name or address}
PI_USER=${RPICAM_USER:-user}
PI_KEY=${RPICAM_SSH_KEY:-}
REMOTE_ROOT=${RPICAM_REMOTE_RUNS:-/home/$PI_USER/rpicam-runs}
LOCAL_ROOT=${RPICAM_LOCAL_RUNS:-$REPO_ROOT/runs/pi}

mkdir -p "$LOCAL_ROOT"

# This is deliberately one-way and has no --delete. A missing/corrupt Pi-side
# file must never erase the Mac safety copy.
if [ -n "$PI_KEY" ]; then
    rsync \
        --archive \
        --partial \
        --human-readable \
        -e "ssh -i $PI_KEY -o BatchMode=yes -o ConnectTimeout=5" \
        "$PI_USER@$PI_HOST:$REMOTE_ROOT/" \
        "$LOCAL_ROOT/"
else
    rsync \
        --archive \
        --partial \
        --human-readable \
        -e "ssh -o BatchMode=yes -o ConnectTimeout=5" \
        "$PI_USER@$PI_HOST:$REMOTE_ROOT/" \
        "$LOCAL_ROOT/"
fi

