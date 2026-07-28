"""Benchmark scenarios (bound to the Google demo feed).

Each entry is (id, group, hypothesis, request). hypothesis = mechanism expected
to win (FC / Code-gen / Clarify). Every request is attempted by both mechanisms.

NOTE: this is a small STUB set for wiring/testing the pipeline. The full 40
transit-domain scenarios are encoded last (see GTFS_Test_Scenarios.docx).
"""

SCENARIOS = [
    ("A1", "A", "FC", "Rename the stop 'Stagecoach Hotel & Casino' to 'Stagecoach Casino'."),
    ("B1", "B", "FC", "Set the City route colour to 1E90FF and its text colour to FFFFFF."),
    ("D1", "D", "Code-gen", "Push every trip on weekday service FULLW 15 minutes later."),
    ("F1", "F", "Clarify", "Make the morning buses come more often."),
]
