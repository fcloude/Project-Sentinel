from src.investigation.statistics import Statistics


class ReportGenerator:

    def __init__(self):

        self.stats = Statistics()

    def generate(self):

        report = f"""
=====================================

Project Sentinel Report

=====================================

Total Events : {self.stats.total_events()}

=====================================
"""

        return report