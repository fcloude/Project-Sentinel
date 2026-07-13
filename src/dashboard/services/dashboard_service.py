from src.dashboard.models.dashboard_state import DashboardState


class DashboardService:

    def __init__(self):

        self.state = DashboardState()

        self.events = []

        self.cameras = []

        self.faces = []

        self.settings = {
            "motion_threshold": 500,
            "face_threshold": 0.60,
            "yolo_threshold": 0.50,
            "telegram_enabled": True,
        }

    # ----------------------------
    # Dashboard
    # ----------------------------

    def get_dashboard_state(self):

        return self.state.to_dict()

    def update_dashboard_state(
        self,
        **kwargs,
    ):

        for key, value in kwargs.items():

            if hasattr(
                self.state,
                key,
            ):

                setattr(
                    self.state,
                    key,
                    value,
                )

    # ----------------------------
    # Events
    # ----------------------------

    def add_event(
        self,
        event,
    ):

        self.events.insert(
            0,
            event,
        )

        self.events = self.events[:100]

        self.state.alerts_today += 1

        self.state.last_event = str(event)

    def get_recent_events(self):

        return self.events

    # ----------------------------
    # Cameras
    # ----------------------------

    def add_camera(
        self,
        name,
        status="Online",
        camera_type="USB",
    ):

        self.cameras.append(
            {
                "name": name,
                "status": status,
                "type": camera_type,
            }
        )

        self.state.camera_count = len(
            self.cameras,
        )

    def remove_camera(
        self,
        name,
    ):

        self.cameras = [
            camera
            for camera in self.cameras
            if camera["name"] != name
        ]

        self.state.camera_count = len(
            self.cameras,
        )

    def get_cameras(self):

        return self.cameras

    # ----------------------------
    # Faces
    # ----------------------------

    def add_face(
        self,
        name,
    ):

        self.faces.append(
            {
                "name": name,
            }
        )

        self.state.known_faces = len(
            self.faces,
        )

    def remove_face(
        self,
        name,
    ):

        self.faces = [
            face
            for face in self.faces
            if face["name"] != name
        ]

        self.state.known_faces = len(
            self.faces,
        )

    def get_faces(self):

        return self.faces

    # ----------------------------
    # Settings
    # ----------------------------

    def get_settings(self):

        return self.settings

    def update_setting(
        self,
        key,
        value,
    ):

        self.settings[key] = value