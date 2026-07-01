from enum import Enum


class CameraType(Enum):
    MOCK = "Mock Camera"
    USB = "USB Camera"
    RTSP = "RTSP Camera"
    IP = "IP Camera"
    ANDROID = "Android Camera"