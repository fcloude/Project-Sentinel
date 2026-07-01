import cv2

from motion.motion_result import MotionResult


class MotionDetector:

    def __init__(self):

        self.previous_frame = None

    def detect(self, frame):

        gray = cv2.cvtColor(
            frame.data,
            cv2.COLOR_BGR2GRAY,
        )

        gray = cv2.GaussianBlur(
            gray,
            (21,21),
            0,
        )

        if self.previous_frame is None:
            self.previous_frame = gray

            return MotionResult(
                False,
                0,
                [],
            )

        difference = cv2.absdiff(
            self.previous_frame,
            gray,
        )

        threshold = cv2.threshold(
            difference,
            25,
            255,
            cv2.THRESH_BINARY,
        )[1]

        threshold = cv2.dilate(
            threshold,
            None,
            iterations=2,
        )

        contours, _ = cv2.findContours(
            threshold,
            cv2.RETR_EXTERNAL,
            cv2.CHAIN_APPROX_SIMPLE,
        )

        boxes = []

        for contour in contours:

            if cv2.contourArea(contour) < 500:

                continue

            x, y, w, h = cv2.boundingRect(contour)

            boxes.append(
                (x, y, w, h)
            )

        self.previous_frame = gray

        return MotionResult(
            len(boxes) > 0,
            len(boxes),
            boxes,
        )