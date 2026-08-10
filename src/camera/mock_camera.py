from src.camera.camera_interface import CameraInterface
from src.camera.frame import Frame


class MockCamera(CameraInterface):

    def __init__(self):
        self._connected = False

    def connect(self) -> bool:
        self._connected = True
        return True

    def disconnect(self) -> None:
        self._connected = False

    def is_connected(self) -> bool:
        return self._connected

    def capture_frame(self) -> Frame:

        if not self._connected:
            raise RuntimeError("Camera is not connected.")

        return Frame(
            source="Mock Camera",
            data="Mock Frame"
        )