#!/bin/bash
set -u
set -o pipefail

if (( $# < 2 )); then
    echo "usage: $0 TEST_NAME COMMAND [ARG ...]" >&2
    exit 2
fi

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(dirname -- "$SCRIPT_DIR")
PI_HOST=${RPICAM_HOST:-169.254.114.23}
PI_USER=${RPICAM_USER:-user}
PI_KEY=${RPICAM_SSH_KEY:-/Users/swith/.ssh/id_ed25519_rpicam}
REMOTE_ROOT=${RPICAM_REMOTE_RUNS:-/home/user/rpicam-runs}

test_name=$1
shift
if [[ ! $test_name =~ ^[A-Za-z0-9._-]+$ ]]; then
    echo "test name may contain only letters, numbers, dot, underscore, and dash" >&2
    exit 2
fi

run_id="$(date -u +%Y%m%dT%H%M%SZ)_${test_name}"
remote_run="$REMOTE_ROOT/$run_id"
printf -v escaped_command '%q ' "$@"

echo "Pi run:  $remote_run"
echo "Mac mirror: $REPO_ROOT/runs/pi/$run_id"

ssh \
    -i "$PI_KEY" \
    -o BatchMode=yes \
    -o ConnectTimeout=5 \
    "$PI_USER@$PI_HOST" \
    "mkdir -p '$remote_run'; cd '$remote_run'; export RPICAM_RUN_DIR='$remote_run'; $escaped_command"
test_status=$?

# Always attempt the pull, including after a failed/interrupted test.
/bin/sh "$SCRIPT_DIR/sync_from_pi.sh"
sync_status=$?

if (( sync_status != 0 )); then
    echo "warning: Pi test completed, but Mac mirroring failed" >&2
    exit "$sync_status"
fi
exit "$test_status"
