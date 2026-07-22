#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(dirname -- "$SCRIPT_DIR")

PI_HOST=${RPICAM_HOST:-169.254.114.23}
PI_USER=${RPICAM_USER:-user}
PI_KEY=${RPICAM_SSH_KEY:-/Users/swith/.ssh/id_ed25519_rpicam}
REMOTE_ROOT=${RPICAM_REMOTE_RUNS:-/home/user/rpicam-runs}
LOCAL_ROOT=${RPICAM_LOCAL_RUNS:-$REPO_ROOT/runs/pi}

mkdir -p "$LOCAL_ROOT"

# This is deliberately one-way and has no --delete. A missing/corrupt Pi-side
# file must never erase the Mac safety copy.
rsync \
    --archive \
    --partial \
    --human-readable \
    -e "ssh -i $PI_KEY -o BatchMode=yes -o ConnectTimeout=5" \
    "$PI_USER@$PI_HOST:$REMOTE_ROOT/" \
    "$LOCAL_ROOT/"

