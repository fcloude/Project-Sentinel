from dataclasses import dataclass


@dataclass(slots=True)
class Detection:

    label: str

    confidence: float

    box: tuple[int, int, int, int]