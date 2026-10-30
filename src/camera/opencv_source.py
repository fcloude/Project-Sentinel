import cv2

from src.camera.camera_exceptions import CameraCaptureError, CameraConnectionError
from src.camera.camera_interface import CameraInterface
from src.camera.frame import Frame

OPEN_TIMEOUT_MS = 5000
READ_TIMEOUT_MS = 5000


class OpenCVSource(CameraInterface):
    """One class for USB webcams, RTSP/HTTP cameras, phone apps and video files.

    Error messages never include the source: network URLs contain passwords.
    """

    def __init__(self, source):
        self.source = source
        self.capture = None

    def connect(self) -> bool:
        if isinstance(self.source, str) and "://" in self.source:
            params = [
                cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, OPEN_TIMEOUT_MS,
                cv2.CAP_PROP_READ_TIMEOUT_MSEC, READ_TIMEOUT_MS,
            ]
            capture = cv2.VideoCapture(self.source, cv2.CAP_FFMPEG, params)
        else:
            capture = cv2.VideoCapture(self.source)

        if not capture.isOpened():
            capture.release()
            raise CameraConnectionError("Unable to open the camera.")

        self.capture = capture
        return True

    def disconnect(self) -> None:
        if self.capture is not None:
            self.capture.release()
            self.capture = None

    def is_connected(self) -> bool:
        return self.capture is not None and self.capture.isOpened()

    def capture_frame(self) -> Frame:
        if not self.is_connected():
            raise CameraConnectionError("Camera is not connected.")

        success, image = self.capture.read()
        if not success or image is None:
            raise CameraCaptureError("Unable to read a frame.")

        return Frame(source="camera", data=image)


def grab_jpeg(source) -> bytes:
    """Connects, grabs ONE frame, returns it as JPEG bytes. Used by 'Test connection'."""
    camera = OpenCVSource(source)
    try:
        camera.connect()
        frame = camera.capture_frame()
    finally:
        camera.disconnect()

    ok, buffer = cv2.imencode(".jpg", frame.data)
    if not ok:
        raise CameraCaptureError("Unable to encode the frame.")
    return buffer.tobytes()
