#!/usr/bin/python3
"""Probe alternating IMX296 exposure controls on queued libcamera requests."""

from __future__ import annotations

import argparse
import time

import libcamera as libcam


def set_manual_controls(request, exposure_us: int, frame_duration_us: int) -> None:
    request.set_control(libcam.controls.ExposureTimeMode, 1)
    request.set_control(libcam.controls.AnalogueGainMode, 1)
    request.set_control(libcam.controls.ExposureTime, exposure_us)
    request.set_control(libcam.controls.AnalogueGain, 1.0)
    request.set_control(
        libcam.controls.FrameDurationLimits,
        (frame_duration_us, frame_duration_us),
    )


def set_exposure_only(request, exposure_us: int) -> None:
    request.set_control(libcam.controls.ExposureTime, exposure_us)


def metadata_by_name(request) -> dict[str, object]:
    return {control.name: value for control, value in request.metadata.items()}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frames", type=int, default=40)
    parser.add_argument("--short-us", type=int, default=93)
    parser.add_argument("--long-us", type=int, default=16_574)
    parser.add_argument("--frame-us", type=int, default=16_667)
    parser.add_argument(
        "--buffers",
        type=int,
        default=4,
        help="Queued request depth; must exceed the IMX296's two-frame control delay",
    )
    parser.add_argument("--output", help="Also write the CSV probe log to this path")
    args = parser.parse_args()

    output_file = open(args.output, "w", encoding="utf-8") if args.output else None

    def emit(line: str) -> None:
        print(line, flush=True)
        if output_file is not None:
            output_file.write(line + "\n")
            output_file.flush()

    manager = libcam.CameraManager.singleton()
    if not manager.cameras:
        raise RuntimeError("no cameras detected")
    camera = manager.cameras[0]
    camera.acquire()

    allocator = None
    try:
        configuration = camera.generate_configuration([libcam.StreamRole.Raw])
        stream_configuration = configuration.at(0)
        stream_configuration.size = libcam.Size(1456, 1088)
        stream_configuration.pixel_format = libcam.PixelFormat("SBGGR10_CSI2P")
        stream_configuration.buffer_count = args.buffers
        status = configuration.validate()
        if status == libcam.CameraConfiguration.Status.Invalid:
            raise RuntimeError("camera rejected RAW configuration")
        if camera.configure(configuration) not in (None, 0):
            raise RuntimeError("camera configuration failed")

        stream = stream_configuration.stream
        allocator = libcam.FrameBufferAllocator(camera)
        if allocator.allocate(stream) < 0:
            raise RuntimeError("buffer allocation failed")
        buffers = allocator.buffers(stream)
        if len(buffers) < args.buffers:
            raise RuntimeError(
                f"requested {args.buffers} buffers, received {len(buffers)}"
            )

        requests = []
        exposures = (args.short_us, args.long_us)
        for index, buffer in enumerate(buffers[: args.buffers]):
            request = camera.create_request(index)
            if request is None:
                raise RuntimeError("request creation failed")
            add_result = request.add_buffer(stream, buffer)
            if add_result not in (None, 0):
                raise RuntimeError("request buffer attachment failed")
            set_manual_controls(request, exposures[index % 2], args.frame_us)
            requests.append(request)

        if camera.start() not in (None, 0):
            raise RuntimeError("camera start failed")
        try:
            for request in requests:
                if camera.queue_request(request) not in (None, 0):
                    raise RuntimeError("initial request queue failed")

            completed = 0
            previous_timestamp = None
            emit("index,cookie,requested_us,actual_us,frame_us,delta_us,sequence")
            while completed < args.frames:
                deadline = time.monotonic() + 2.0
                ready_requests = []
                while not ready_requests and time.monotonic() < deadline:
                    ready_requests = manager.get_ready_requests()
                    if not ready_requests:
                        time.sleep(0.001)
                if not ready_requests:
                    raise TimeoutError("camera request timed out")
                for request in ready_requests:
                    if request.status != libcam.Request.Status.Complete:
                        raise RuntimeError(f"request failed: {request.status}")
                    metadata = metadata_by_name(request)
                    timestamp = int(metadata.get("SensorTimestamp", 0))
                    delta_us = (
                        ""
                        if previous_timestamp is None
                        else f"{(timestamp - previous_timestamp) / 1000:.0f}"
                    )
                    requested = exposures[request.cookie % 2]
                    emit(
                        f"{completed},{request.cookie},{requested},"
                        f"{metadata.get('ExposureTime')},"
                        f"{metadata.get('FrameDuration')},{delta_us},"
                        f"{request.sequence}"
                    )
                    previous_timestamp = timestamp
                    completed += 1
                    if completed >= args.frames:
                        continue

                    request.reuse()
                    set_manual_controls(request, requested, args.frame_us)
                    if camera.queue_request(request) not in (None, 0):
                        raise RuntimeError("request requeue failed")
        finally:
            camera.stop()
    finally:
        if allocator is not None:
            allocator = None
        camera.release()
        if output_file is not None:
            output_file.close()


if __name__ == "__main__":
    main()
