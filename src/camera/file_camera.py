import cv2

from src.camera.camera_exceptions import CameraCaptureError, CameraConnectionError
from src.camera.camera_interface import CameraInterface
from src.camera.frame import Frame


class FileCamera(CameraInterface):
    """Plays a video file in a loop, so the engine runs without a webcam."""

    def __init__(self, path: str, loop: bool = True):
        self.path = str(path)
        self.loop = loop
        self.capture = None

    def connect(self) -> bool:
        self.capture = cv2.VideoCapture(self.path)

        if not self.capture.isOpened():
            self.capture = None
            raise CameraConnectionError(f"Unable to open video file {self.path}")

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

        if not success and self.loop:
            self.capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
            success, image = self.capture.read()

        if not success:
            raise CameraCaptureError("End of video file.")

        return Frame(source=f"File: {self.path}", data=image)
