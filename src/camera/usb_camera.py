import cv2

from src.camera.camera_interface import CameraInterface
from src.camera.frame import Frame
from src.camera.camera_exceptions import CameraConnectionError, CameraCaptureError


class USBCamera(CameraInterface):

    def __init__(self, index: int = 0):
        self.index = index
        self.capture = None

    def connect(self) -> bool:
        self.capture = cv2.VideoCapture(self.index)

        if not self.capture.isOpened():
            raise CameraConnectionError(
                f"Unable to open camera {self.index}"
            )

        return True

    def disconnect(self) -> None:
        if self.capture:
            self.capture.release()

    def is_connected(self) -> bool:
        return (
            self.capture is not None
            and self.capture.isOpened()
        )

    def capture_frame(self) -> Frame:

        if not self.is_connected():
            raise CameraConnectionError(
                "Camera is not connected."
            )

        success, image = self.capture.read()

        if not success:
            raise CameraCaptureError(
                "Unable to capture frame."
            )

        return Frame(
            source="USB Camera",
            data=image,
        )