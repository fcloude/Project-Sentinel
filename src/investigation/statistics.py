from src.database.repositories.event_repository import EventRepository


class Statistics:

    def __init__(self):

        self.events = EventRepository()

    def total_events(self):

        return self.events.count_events()