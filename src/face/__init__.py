"""Legacy InsightFace-based face modules (superseded by ``src/faces``, see ADR-004).

Importing this package must not import the optional ``insightface`` dependency: the
supported pipeline lives in ``src.faces`` and the rest of the application (and the tests)
need ``src.face.database`` without that package installed. The public names are resolved
lazily, on first access, and this module is intentionally side-effect free.
"""
from importlib import import_module

_EXPORTS = {
    "FaceDatabase": ".database",
    "FaceEmbedding": ".embedding",
    "FaceDetector": ".face_detector",
    "FaceManager": ".face_manager",
    "FaceMatcher": ".face_matcher",
    "FaceRegistry": ".face_registry",
    "RecognitionResult": ".recognition_result",
}

__all__ = list(_EXPORTS)


def __getattr__(name: str):
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(import_module(module_name, __name__), name)
