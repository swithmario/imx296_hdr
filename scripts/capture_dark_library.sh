#!/bin/bash
set -eu

if (( $# < 2 )); then
    echo "usage: $0 RECORDER.py OUTPUT_ROOT [EXPOSURE_US ...]" >&2
    exit 2
fi

recorder=$1
output_root=$2
shift 2
if (( $# )); then
    exposures_us=("$@")
else
    exposures_us=(1000 2000 5000 10000 20000 50000 100000 200000 500000 1000000)
fi

mkdir -p "$output_root"
for exposure_us in "${exposures_us[@]}"; do
    point_dir="$output_root/${exposure_us}us"
    mkdir -p "$point_dir"
    frame_us=$((exposure_us + 2000))
    if (( frame_us < 16667 )); then
        frame_us=16667
    fi

    echo "Capturing darks at requested ${exposure_us} us"
    python3 "$recorder" \
        --frames 18 --discard 8 \
        --short-us "$exposure_us" --long-us "$exposure_us" \
        --frame-us "$frame_us" --buffers 4 --output-dir "$point_dir" &
    capture_pid=$!

    # The current libcamera Python singleton can leave a manager thread alive
    # after the recorder has flushed its final manifest. The manifest is the
    # last write, so its appearance is a safe completion signal.
    timeout_s=$((30 + (18 * frame_us + 999999) / 1000000))
    if (( timeout_s < 60 )); then
        timeout_s=60
    fi
    deadline=$((SECONDS + timeout_s))
    while [[ ! -s "$point_dir/manifest.json" ]]; do
        if ! kill -0 "$capture_pid" 2>/dev/null; then
            wait "$capture_pid"
            echo "capture exited before writing manifest" >&2
            exit 1
        fi
        if (( SECONDS >= deadline )); then
            kill "$capture_pid" 2>/dev/null || true
            wait "$capture_pid" 2>/dev/null || true
            echo "capture timed out at ${exposure_us} us" >&2
            exit 1
        fi
        sleep 0.1
    done
    kill "$capture_pid" 2>/dev/null || true
    wait "$capture_pid" 2>/dev/null || true
done
