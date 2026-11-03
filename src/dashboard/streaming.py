import time


def mjpeg_frames(worker, interval=0.2, max_seconds=3600, clock=time.monotonic, sleep=time.sleep):
    """Yields a multipart MJPEG stream (what an <img> tag can display) from a CameraWorker."""
    started = clock()
    last_seq = -1

    while clock() - started < max_seconds and not getattr(worker, "stopped", False):
        jpeg, seq = worker.latest_jpeg()

        if jpeg is not None and seq != last_seq:
            last_seq = seq
            yield (
                b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                + str(len(jpeg)).encode()
                + b"\r\n\r\n"
                + jpeg
                + b"\r\n"
            )

        sleep(interval)
