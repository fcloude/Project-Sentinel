from abc import ABC, abstractmethod

from src.camera.frame import Frame


class CameraInterface(ABC):

    @abstractmethod
    def connect(self) -> bool:
        pass

    @abstractmethod
    def disconnect(self) -> None:
        pass

    @abstractmethod
    def capture_frame(self) -> Frame:
        pass

    @abstractmethod
    def is_connected(self) -> bool:
        pass