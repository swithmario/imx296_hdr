#!/bin/bash
set -u
set -o pipefail

if (( $# < 2 )); then
    echo "usage: $0 TEST_NAME COMMAND [ARG ...]" >&2
    exit 2
fi

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(dirname -- "$SCRIPT_DIR")
PI_HOST=${RPICAM_HOST:?Set RPICAM_HOST to the Raspberry Pi host name or address}
PI_USER=${RPICAM_USER:-user}
PI_KEY=${RPICAM_SSH_KEY:-}
REMOTE_ROOT=${RPICAM_REMOTE_RUNS:-/home/$PI_USER/rpicam-runs}

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

ssh_options=(
    -o BatchMode=yes
    -o ConnectTimeout=5
)
if [[ -n $PI_KEY ]]; then
    ssh_options+=(-i "$PI_KEY")
fi

ssh "${ssh_options[@]}" \
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
