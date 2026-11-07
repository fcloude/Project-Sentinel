from src.dashboard.models.dashboard_state import DashboardState


class DashboardService:
    """In-memory view model for the dashboard pages.

    The engine pushes live status through /api/status; this service only keeps the
    small amount of presentation state the templates render.
    """

    def __init__(self):
        self.state = DashboardState()
        self.events = []
        self.cameras = []
        self.faces = []
        self.settings = {}

    def get_dashboard_state(self):
        return self.state.to_dict()

    def update_dashboard_state(self, **kwargs):
        for key, value in kwargs.items():
            if hasattr(self.state, key):
                setattr(self.state, key, value)

    def add_event(self, event):
        self.events.insert(0, event)
        self.state.alerts_today += 1
        self.state.last_event = str(event)

    def get_recent_events(self, limit=10):
        return self.events[:limit]

    def add_camera(self, camera):
        self.cameras.append(camera)
        self.state.camera_count = len(self.cameras)

    def remove_camera(self, index):
        del self.cameras[index]
        self.state.camera_count = len(self.cameras)

    def get_cameras(self):
        return self.cameras

    def add_face(self, face):
        self.faces.append(face)
        self.state.known_faces = len(self.faces)

    def remove_face(self, index):
        del self.faces[index]
        self.state.known_faces = len(self.faces)

    def get_faces(self):
        return self.faces

    def get_settings(self):
        return self.settings

    def update_setting(self, key, value):
        self.settings[key] = value
