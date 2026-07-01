from dataclasses import dataclass

@dataclass(slots=True)
class MotionResult:
    detected: bool
    contour_count: int
    bounding_boxes: list