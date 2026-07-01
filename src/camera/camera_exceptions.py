class CameraError(Exception):
    """Base camera exception."""


class CameraConnectionError(CameraError):
    """Raised when connection fails."""


class CameraCaptureError(CameraError):
    """Raised when frame capture fails."""