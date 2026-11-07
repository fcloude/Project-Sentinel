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


def _sse_message(unread, rows, last_id=None):
    import json

    payload = {
        "unread": unread,
        "new": [
            {
                "id": r["id"],
                "title": r["title"],
                "body": r["body"],
                "camera": r["camera_name"],
                "time": r["created_at"],
            }
            for r in rows
        ],
    }
    prefix = f"id: {last_id}\n" if last_id is not None else ""
    return f"{prefix}data: {json.dumps(payload)}\n\n"


def sse_events(repo, conn, last_id, unread, poll=2.0, max_seconds=3600, heartbeat=15.0,
               clock=time.monotonic, sleep=time.sleep):
    """Server-sent events: tells the page about new notifications as they arrive."""
    try:
        yield _sse_message(unread, [])
        started = last_beat = clock()

        while clock() - started < max_seconds:
            sleep(poll)
            rows = repo.inbox_after(last_id)
            if rows:
                last_id = rows[-1]["id"]
                yield _sse_message(repo.unread_count(), rows, last_id)
                last_beat = clock()
            elif clock() - last_beat >= heartbeat:
                yield ": keepalive\n\n"
                last_beat = clock()
    finally:
        conn.close()
