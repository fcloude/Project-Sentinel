from database.repositories.event_repository import EventRepository

from database.repositories.detection_repository import DetectionRepository

from investigation.report_generator import ReportGenerator


class InvestigationEngine:

    def __init__(self):

        self.events = EventRepository()

        self.detections = DetectionRepository()

        self.report = ReportGenerator()

    def events_history(self):

        return self.events.get_all_events()

    def last_seen(self, person):

        return self.detections.get_last_seen(person)

    def unknown_people(self):

        return self.detections.get_unknown_people()

    def daily_report(self):

        return self.report.generate()