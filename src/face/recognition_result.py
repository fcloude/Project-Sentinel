from dataclasses import dataclass


@dataclass(slots=True)
class RecognitionResult:
    recognized: bool
    name: str
    confidence: float
    location: tuple[int, int, int, int]