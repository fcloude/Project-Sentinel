import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import cv2
import numpy as np

from src.app_logging import get_logger
from src.database.people_repository import PeopleRepository, SettingsRepository
from src.errors import UserFacingError
from src.faces.backends import MODEL_ID, load_default_backends
from src.faces.index import FaceIndex
from src.faces.quality import check_enrolment_face

logger = get_logger(__name__)

# Cosine-similarity thresholds for SFace (0.363 is OpenCV's recommended value).
STRICTNESS = {"strict": 0.45, "balanced": 0.363, "lenient": 0.30}
DEFAULT_STRICTNESS = "balanced"

UNKNOWN_DEDUPE_THRESHOLD = 0.45  # same unknown person seen again -> count it, don't add a card
UNKNOWN_RETENTION_DAYS = 7
MAX_IMAGE_SIDE = 4000


class FaceServiceError(UserFacingError):
    pass


@dataclass
class FaceResult:
    recognized: bool
    name: str
    person_id: object
    confidence: float
    box: tuple
    embedding: object


@dataclass
class EnrolOutcome:
    filename: str
    ok: bool
    reason: str = None


def decode_image(data: bytes):
    """Bytes -> BGR image, or None if it isn't a readable image. Huge images are shrunk."""
    if not data:
        return None
    try:
        image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    except cv2.error:
        return None
    if image is None:
        return None

    height, width = image.shape[:2]
    longest = max(height, width)
    if longest > MAX_IMAGE_SIDE:
        scale = MAX_IMAGE_SIDE / longest
        image = cv2.resize(
            image, (int(width * scale), int(height * scale)), interpolation=cv2.INTER_AREA
        )
    return image


class FaceService:
    """Finds faces, recognises people, enrols new ones, and keeps the unknown-face inbox.

    Creating it is cheap. The AI models load the first time they're needed, so
    pages that only list people work even if the model files are missing.
    """

    def __init__(self, db_factory, backends_loader=load_default_backends,
                 model_id=MODEL_ID, unknown_dir=None):
        self._db_factory = db_factory
        self._backends_loader = backends_loader
        self.model_id = model_id

        if unknown_dir is None:
            from src.database import manager

            unknown_dir = Path(manager.settings.database_path).parent / "unknown_faces"
        self.unknown_dir = Path(unknown_dir)

        self.index = FaceIndex()
        self.threshold = STRICTNESS[DEFAULT_STRICTNESS]
        self.stale_embeddings = 0

        self._lock = threading.RLock()
        self._conn = None
        self._backends = None

    # ---- plumbing -----------------------------------------------------------

    def _people(self):
        if self._conn is None:
            self._conn = self._db_factory()
        return PeopleRepository(self._conn)

    def _get_backends(self):
        if self._backends is None:
            self._backends = self._backends_loader()
        return self._backends

    def ensure_ready(self):
        """Loads the models (raises a friendly error if missing) and the known faces."""
        with self._lock:
            self._get_backends()
            self.reload()

    def reload(self):
        """Re-reads people and the strictness setting. Call after any change."""
        with self._lock:
            repo = self._people()
            self.index.load(repo.all_embeddings(self.model_id))
            level = SettingsRepository(self._conn).get("face_strictness", DEFAULT_STRICTNESS)
            self.threshold = STRICTNESS.get(level, STRICTNESS[DEFAULT_STRICTNESS])
            self.stale_embeddings = repo.count_stale(self.model_id)

    # ---- recognising ------------------------------------------------------------

    def process(self, frame):
        """All faces in a camera frame -> list of FaceResult."""
        image = frame.data
        with self._lock:
            detector, embedder = self._get_backends()
            results = []
            for face in detector.detect(image):
                embedding = embedder.embed(image, face)
                match = self.index.match(embedding, self.threshold)
                results.append(
                    FaceResult(
                        recognized=match.recognized,
                        name=match.name if match.recognized else "Unknown",
                        person_id=match.person_id if match.recognized else None,
                        confidence=max(match.score, 0.0),
                        box=face.box,
                        embedding=embedding,
                    )
                )
            return results

    # ---- enrolling ----------------------------------------------------------------

    def enroll_photos(self, person_id, photos):
        """photos: [(filename, bytes)] -> [EnrolOutcome]. Bad photos are rejected with a reason."""
        outcomes = []
        with self._lock:
            detector, embedder = self._get_backends()
            repo = self._people()

            for filename, data in photos:
                image = decode_image(data)
                if image is None:
                    outcomes.append(EnrolOutcome(filename, False, "That file is not a readable image."))
                    continue

                face, reason = check_enrolment_face(image, detector.detect(image))
                if face is None:
                    outcomes.append(EnrolOutcome(filename, False, reason))
                    continue

                repo.add_embedding(person_id, self.model_id, embedder.embed(image, face), quality=face.score)
                outcomes.append(EnrolOutcome(filename, True))

            if any(o.ok for o in outcomes):
                self.reload()
        return outcomes

    # ---- unknown-face inbox ----------------------------------------------------------

    def record_unknown(self, camera_id, result, frame):
        """Saves an unknown face for review, or counts a repeat sighting of one already saved."""
        with self._lock:
            repo = self._people()
            now = datetime.now(timezone.utc)
            since = (now - timedelta(hours=24)).isoformat()

            for unknown_id, vector in repo.recent_unknown_vectors(self.model_id, since):
                if float(np.dot(vector, result.embedding)) >= UNKNOWN_DEDUPE_THRESHOLD:
                    repo.bump_unknown(unknown_id, now.isoformat())
                    return unknown_id

            path = self._save_crop(frame.data, result.box, camera_id, now)
            if path is None:
                return None
            return repo.add_unknown(camera_id, self.model_id, result.embedding, str(path), now.isoformat())

    def _save_crop(self, image, box, camera_id, now):
        x, y, w, h = box
        margin_x, margin_y = int(w * 0.25), int(h * 0.25)
        image_height, image_width = image.shape[:2]
        x0, y0 = max(x - margin_x, 0), max(y - margin_y, 0)
        x1, y1 = min(x + w + margin_x, image_width), min(y + h + margin_y, image_height)
        crop = image[y0:y1, x0:x1]
        if crop.size == 0:
            return None

        longest = max(crop.shape[:2])
        if longest > 160:
            scale = 160 / longest
            crop = cv2.resize(crop, (int(crop.shape[1] * scale), int(crop.shape[0] * scale)))

        folder = self.unknown_dir / str(camera_id)
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / (now.strftime("%Y%m%d_%H%M%S_%f") + ".jpg")
        return path if cv2.imwrite(str(path), crop) else None

    def promote_unknown(self, unknown_id, name=None, person_id=None, consent=False):
        """Turns an unknown face into a known person (new, or added to an existing one)."""
        with self._lock:
            repo = self._people()
            row = repo.get_unknown(unknown_id)
            if row is None:
                raise FaceServiceError("That face is no longer in the list.")

            if person_id is None:
                name = (name or "").strip()
                if not 1 <= len(name) <= 50:
                    raise FaceServiceError("Give the person a name (1-50 characters).")
                if not consent:
                    raise FaceServiceError("Please confirm that this person agreed to be recognised.")
                if repo.person_exists(name):
                    raise FaceServiceError(f"'{name}' already exists. Choose them from the list instead.")
                person_id = repo.create_person(name, consent=True)
            elif repo.get_person(person_id) is None:
                raise FaceServiceError("That person no longer exists.")

            repo.add_embedding(person_id, row["model_id"], row["vector"], quality=1.0)
            self._remove_unknown(repo, row)
            self.reload()
            return person_id

    def dismiss_unknown(self, unknown_id):
        with self._lock:
            repo = self._people()
            row = repo.get_unknown(unknown_id)
            if row is not None:
                self._remove_unknown(repo, row)

    def _remove_unknown(self, repo, row):
        repo.delete_unknown(row["id"])
        self._delete_crop(row["crop_path"])

    def _delete_crop(self, crop_path):
        try:
            path = Path(crop_path).resolve()
            if self.unknown_dir.resolve() in path.parents and path.is_file():
                path.unlink()
        except OSError:
            logger.warning("Could not delete an unknown-face image.")

    def purge_unknowns(self, days=UNKNOWN_RETENTION_DAYS):
        """Retention: unknown faces are deleted after N days."""
        with self._lock:
            before = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
            for crop_path in self._people().delete_old_unknowns(before):
                self._delete_crop(crop_path)


_service = None
_service_lock = threading.Lock()


def get_face_service() -> FaceService:
    """The one shared service (web pages and the engine use the same one)."""
    global _service
    with _service_lock:
        if _service is None:
            from src.database.manager import DatabaseManager

            _service = FaceService(lambda: DatabaseManager().get_connection())
            try:
                _service.reload()
            except Exception:
                logger.exception("Could not load known faces yet")
        return _service
