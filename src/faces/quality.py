import cv2

MIN_DETECTION_SCORE = 0.7
MIN_FACE_WIDTH = 80
MIN_SHARPNESS = 30.0  # variance of the Laplacian on a 112x112 face crop; tune with real photos


def sharpness(image, box) -> float:
    x, y, w, h = box
    image_height, image_width = image.shape[:2]
    x0, y0 = max(int(x), 0), max(int(y), 0)
    x1, y1 = min(int(x + w), image_width), min(int(y + h), image_height)
    if x1 - x0 < 2 or y1 - y0 < 2:
        return 0.0

    gray = cv2.cvtColor(image[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, (112, 112), interpolation=cv2.INTER_AREA)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def check_enrolment_face(image, faces):
    """Returns (face, None) if the photo is good enough, else (None, friendly reason)."""
    if not faces:
        return None, "No face found. Use a clear, front-facing photo with good light."
    if len(faces) > 1:
        return None, "More than one face found. Use a photo of only this person."

    face = faces[0]

    if face.score < MIN_DETECTION_SCORE:
        return None, "The face is not clear enough. Face the camera and use better light."
    if face.box[2] < MIN_FACE_WIDTH:
        return None, (
            f"The face is too small ({face.box[2]} px wide, need {MIN_FACE_WIDTH}+). "
            "Move closer or use a higher-resolution photo."
        )
    if sharpness(image, face.box) < MIN_SHARPNESS:
        return None, "The photo is blurry. Hold the camera steady and use better light."

    return face, None
