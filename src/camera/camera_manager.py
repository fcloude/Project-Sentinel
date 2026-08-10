from src.camera.camera_interface import CameraInterface
from src.camera.frame import Frame


class CameraManager:

    def __init__(self, camera: CameraInterface):
        self.camera = camera

    def connect(self):

        return self.camera.connect()

    def disconnect(self):

        self.camera.disconnect()

    def capture_frame(self) -> Frame:

        return self.camera.capture_frame()

    def is_connected(self):

        return self.camera.is_connected()