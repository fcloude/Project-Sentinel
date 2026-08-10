from pathlib import Path
import cv2
from src.camera.frame import Frame
from src.face.database import FaceDatabase
from src.face.embedding import FaceEmbedding
from src.face.face_detector import FaceDetector
from src.face.face_matcher import FaceMatcher
image_path = Path(__file__).parent.parent / '8454.jpg'
image = cv2.imread(str(image_path))
frame = Frame(source='test', data=image)
detector = FaceDetector()
faces = detector.detect(frame)
database = FaceDatabase()
embedding = FaceEmbedding()
if faces:
    database.add_face('Aryan', embedding.generate(faces[0]))
matcher = FaceMatcher()
for result in map(matcher.match, faces):
    print()
    print('Recognized :', result.recognized)
    print('Name       :', result.name)
    print('Confidence :', result.confidence)
    print('Location   :', result.location)
