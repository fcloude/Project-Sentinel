import threading
import time

from src.app_logging import get_logger
from src.camera.opencv_source import OpenCVSource
from src.camera.url_utils import capture_source
from src.camera.worker import CameraWorker
from src.database import manager
from src.database.camera_repository import CameraRepository
from src.database.manager import DatabaseManager
from src.database.repository import EventRepository
from src.database.schema import initialize_database
from src.engine.analyzer import CameraAnalyzer
from src.errors import UserFacingError
from src.events import event_types
from src.events.event_manager import EventManager
from src.events.queued_subscriber import QueuedSubscriber
from src.motion.snapshot import SnapshotSaver
from src.notifications.service import build_dispatcher
from src.security.crypto import SecretBox, get_encryption_keys

logger = get_logger(__name__)

# Events the notification rules can react to.
DISPATCH_TYPES = (
    event_types.MOTION_DETECTED,
    event_types.PERSON_DETECTED,
    event_types.FACE_RECOGNIZED,
    event_types.UNKNOWN_PERSON,
)


# ----------------------------------------------------------------------
# Default (real) building blocks. Tests replace them with fakes.
# ----------------------------------------------------------------------

def load_enabled_cameras():
    initialize_database()
    conn = DatabaseManager().get_connection()
    try:
        box = SecretBox(get_encryption_keys())
        return CameraRepository(conn, box).list_enabled()
    finally:
        conn.close()


def default_source_factory(camera):
    source = capture_source(camera["kind"], camera["source"])
    return lambda: OpenCVSource(source)


def default_models_loader():
    from src.faces.service import get_face_service

    logger.info("Loading face models...")
    service = get_face_service()
    service.ensure_ready()  # raises a friendly error if the model files are missing
    return service


# ----------------------------------------------------------------------


class SentinelEngine:
    """Runs every enabled camera: reader -> analyzer -> events -> database / alerts."""

    def __init__(
        self,
        camera_loader=load_enabled_cameras,
        source_factory=default_source_factory,
        models_loader=default_models_loader,
        dispatcher_factory=build_dispatcher,
        snapshot_dir=None,
        fps_override=None,
        persist_events=True,
        worker_options=None,
    ):
        self.camera_loader = camera_loader
        self.source_factory = source_factory
        self.models_loader = models_loader
        self.dispatcher_factory = dispatcher_factory
        self.snapshot_dir = snapshot_dir
        self.fps_override = fps_override
        self.persist_events = persist_events
        self.worker_options = worker_options or {}

        self.events = EventManager()

        self.running = False
        self.loading = False
        self.error = None

        self._thread = None
        self._stop_event = threading.Event()
        self._lock = threading.RLock()
        self._inference_lock = threading.Lock()

        self._models = None
        self._workers = {}
        self._analyzers = []
        self._sinks = []  # (QueuedSubscriber, [event types it listens to])

    # ---- controls -------------------------------------------------------

    def start(self):
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                if not self._stop_event.is_set():
                    logger.info("Sentinel Engine already running.")
                    return
                self._thread.join(20)
                if self._thread.is_alive():
                    logger.warning("Previous engine run is still shutting down.")
                    return

            logger.info("Starting Sentinel Engine...")
            self._stop_event.clear()
            self.running = True
            self.loading = self._models is None
            self.error = None

            self._thread = threading.Thread(
                target=self._run, name="SentinelEngine", daemon=True
            )
            self._thread.start()

    def stop(self):
        with self._lock:
            if not self.running:
                return
            logger.info("Stopping Sentinel Engine...")
            self._stop_event.set()
            thread = self._thread

        if thread is not None and thread is not threading.current_thread():
            thread.join(20)

    def restart(self):
        self.stop()
        self.start()

    def get_worker(self, camera_id):
        return self._workers.get(camera_id)

    @property
    def status(self):
        return {
            "running": self.running,
            "thread_alive": bool(self._thread and self._thread.is_alive()),
            "loading": self.loading,
            "error": self.error,
            "cameras": [w.status() for w in list(self._workers.values())],
        }

    # ---- the engine thread ----------------------------------------------

    def _run(self):
        try:
            if self._models is None:
                try:
                    self._models = self.models_loader()
                finally:
                    self.loading = False

            if self._stop_event.is_set():
                return

            cameras = self.camera_loader()
            if not cameras:
                self.error = (
                    "No cameras yet. Add one on the Cameras page, then press Restart."
                )
                logger.warning(self.error)

            self._start_sinks()

            saver = SnapshotSaver(self.snapshot_dir)
            for camera in cameras:
                self._start_camera(camera, saver)

            last_purge = 0.0
            while not self._stop_event.wait(1.0):
                if time.monotonic() - last_purge > 3600:
                    last_purge = time.monotonic()
                    self._purge_old_unknown_faces()

        except UserFacingError as error:
            logger.error("Sentinel Engine could not start: %s", error)
            self.error = str(error)
        except Exception:
            logger.exception("Sentinel Engine crashed.")
            self.error = "The engine stopped because of an error. See the log for details."
        finally:
            self._shutdown()

    def _purge_old_unknown_faces(self):
        purge = getattr(self._models, "purge_unknowns", None)
        if purge is None:
            return
        try:
            purge()
        except Exception:
            logger.exception("Could not delete old unknown faces")

    def _start_camera(self, camera, saver):
        worker = CameraWorker(
            camera["id"],
            camera["name"],
            self.source_factory(camera),
            pace_fps=15 if camera["kind"] == "file" else None,
            **self.worker_options,
        )
        worker.start()
        self._workers[camera["id"]] = worker

        analyzer = CameraAnalyzer(
            camera=camera,
            worker=worker,
            publish=self.events.publish,
            get_models=lambda: self._models,
            inference_lock=self._inference_lock,
            snapshot_saver=saver,
            fps=self.fps_override or camera.get("detection_fps") or 3,
        )
        analyzer.start()
        self._analyzers.append(analyzer)

    def _start_sinks(self):
        """Saving events and sending alerts happen on their own threads."""
        if self.persist_events:
            initialize_database()
            persist = QueuedSubscriber(EventRepository().save, "event-store")
            persist.start()
            self.events.subscribe("*", persist)
            self._sinks.append((persist, ["*"]))

        dispatcher = self.dispatcher_factory()
        if dispatcher is not None:
            sink = QueuedSubscriber(dispatcher.handle, "alerts")
            sink.start()
            for event_type in DISPATCH_TYPES:
                self.events.subscribe(event_type, sink)
            self._sinks.append((sink, list(DISPATCH_TYPES)))

    def _shutdown(self):
        for analyzer in self._analyzers:
            analyzer.stop()
        for worker in self._workers.values():
            worker.stop()

        for sink, types in self._sinks:
            for event_type in types:
                self.events.unsubscribe(event_type, sink)
            sink.stop()

        self._analyzers = []
        self._workers = {}
        self._sinks = []
        self.running = False
        logger.info("Sentinel Engine stopped.")
