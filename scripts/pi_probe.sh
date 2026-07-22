#!/bin/sh
set -eu

section() {
    printf '\n[%s]\n' "$1"
}

section system
tr -d '\000' </proc/device-tree/model
printf '\n'
uname -a
cat /etc/os-release

section camera_tools
rpicam-hello --version 2>&1 || true
python3 -c 'from importlib.metadata import version; print("picamera2", version("picamera2"))' 2>&1 || true

section camera_list
rpicam-hello --list-cameras 2>&1 || true

section camera_info_python
python3 - <<'PY' 2>&1 || true
from pprint import pprint

from picamera2 import Picamera2

pprint(Picamera2.global_camera_info())
PY

section media_devices
for device in /dev/media* /dev/video* /dev/v4l-subdev*; do
    [ -e "$device" ] && printf '%s\n' "$device"
done

section storage
lsblk -o NAME,SIZE,FSTYPE,FSVER,LABEL,UUID,MOUNTPOINTS,MODEL
df -hT

section network
ip -brief address

section thermal
vcgencmd measure_temp 2>/dev/null || true
vcgencmd get_throttled 2>/dev/null || true

