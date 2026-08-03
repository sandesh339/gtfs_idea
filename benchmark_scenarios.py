"""Benchmark scenarios, per feed.

Each entry is (id, group, hypothesis, request). hypothesis = the mechanism
expected to win (FC / Code-gen / Clarify). Every editing request is attempted by
BOTH mechanisms; under-specified (Group F) requests should trigger a clarify.

The 40 templates (Groups A-F) come from GTFS_Test_Scenarios.docx. They are
instantiated per feed against that feed's own routes/stops/services, so the same
task is tested at every scale.

MBTA binding: a 10-route slice (data/mbta10/) spanning bus routes 1, 66, 77, 111,
39; subway Red/Orange/Green-B/Blue; and the Providence/Stoughton commuter line.
"""

# --- Google demo feed (small control) -------------------------------------
DEMO_SCENARIOS = [
    ("A1", "A", "FC", "Rename the stop 'Stagecoach Hotel & Casino' to 'Stagecoach Casino'."),
    ("B1", "B", "FC", "Set the City route colour to 1E90FF and its text colour to FFFFFF."),
    ("D1", "D", "Code-gen", "Push every trip on weekday service FULLW 15 minutes later."),
    ("F1", "F", "Clarify", "Make the morning buses come more often."),
]

# --- MBTA 10-route slice (large city) -------------------------------------
# Entities are spread across the 10 routes so the mix exercises bus + subway +
# commuter rail. Service_ids are real slice services (verified present).
MBTA_SCENARIOS = [
    # Group A - Stop & Station Attributes (leans FC)
    ("A1", "A", "FC", "Rename the stop 'Nubian' to 'Nubian Square'."),
    ("A2", "A", "FC", "Move the stop 'Massachusetts Ave @ Wendell St' to 42.3888, -71.1152."),
    ("A3", "A", "FC", "Mark the stop 'Beachmont' as wheelchair accessible."),
    ("A4", "A", "FC", "Set the fare zone (zone_id) of stop 'Sharon' to 'CR-zone-4'."),
    ("A5", "A", "FC", "Add the description 'Elevator to the inbound platform.' to stop 'Wollaston'."),
    ("A6", "A", "FC", "Set the stop_code of stop 'Harvard Avenue' to 'GB-HAV'."),

    # Group B - Route & Agency Branding (leans FC)
    ("B1", "B", "FC", "Set route 66's colour to 1E90FF and its text colour to FFFFFF."),
    ("B2", "B", "FC", "Rename route 39's long name to 'Forest Hills - Back Bay via Huntington'."),
    ("B3", "B", "FC", "Change route 111's short name to '111X'."),
    ("B4", "B", "FC", "Change the agency phone number to (617) 222-3200."),
    ("B5", "B", "FC", "Update the agency URL to https://www.mbta.com."),
    ("B6", "B", "FC", "Set route 77's route_url to https://www.mbta.com/schedules/77."),

    # Group C - Service Frequency & Span (leans FC; C6 code-gen)
    ("C1", "C", "FC", "Make weekday service BUS20263-hba36011-Weekday-02 also run on Saturdays."),
    ("C2", "C", "FC", "Stop running service BUS20263-hbc36017-Sunday-02 on Sundays."),
    ("C3", "C", "FC", "Change service BUS20263-hbc36sn1-Weekday-02's calendar to end on 20260815."),
    ("C4", "C", "FC", "Add a no-service exception for service DIV20263-hmo36ct1-Weekday-01 on 20260525."),
    ("C5", "C", "FC", "Remove the last evening trip on route 39."),
    ("C6", "C", "Code-gen", "Add an extra weekday trip on route 77 departing at 09:00, copying an existing trip's stop pattern with matching offsets."),

    # Group D - Timetable & Travel-Time Engineering (leans Code-gen)
    ("D1", "D", "Code-gen", "Push every trip on weekday service DIV20263-hms36pk1-Weekday-01 15 minutes later."),
    ("D2", "D", "Code-gen", "Fill the blank arrival/departure times on trip 78657286 by linear interpolation between timed stops."),
    ("D3", "D", "Code-gen", "Add 2 minutes of dwell time at stop 'Downtown Crossing' on every trip of the Orange Line."),
    ("D4", "D", "Code-gen", "Speed up the segment between 'Packard's Corner' and 'Harvard Avenue' on the Green Line B by 1 minute."),
    ("D5", "D", "Code-gen", "Insert a new stop 'Mass Ave @ Marlborough St' at 42.3512, -71.0846 on route 1 between 'Massachusetts Ave @ Newbury St' and 'Massachusetts Ave @ Beacon St', adding 1 minute of travel."),
    ("D6", "D", "Code-gen", "Remove stop 'Massachusetts Ave @ Sidney St' from route 1 and close the time gap."),
    ("D7", "D", "Code-gen", "Shift only the afternoon trips of route 39 (departing after 15:00) 10 minutes earlier."),
    ("D8", "D", "Code-gen", "Add a uniform 1-minute running-time increase between every consecutive stop on route 77."),

    # Group E - Network Topology & Trip Structure (leans Code-gen)
    ("E1", "E", "Code-gen", "Create return-direction trips (direction_id = 1) for route 111 by mirroring the outbound trips."),
    ("E2", "E", "Code-gen", "Split the Orange Line at 'Downtown Crossing' into 'Orange North' and 'Orange South'."),
    ("E3", "E", "Code-gen", "Merge trips 76328279 and 76328280 into a single continuous through-trip."),
    ("E4", "E", "Code-gen", "Extend route 77 past 'Arlington Heights Busway' with 'Heights Loop North' (42.4205, -71.1760) and 'Heights Loop South' (42.4190, -71.1745), 2 and 4 minutes later."),
    ("E5", "E", "Code-gen", "Add a new weekday route 'Cross-City Express' (route_id XCE) serving 'Nubian', 'Downtown Crossing', 'Harvard' in order, 8 minutes between stops, first trip at 07:30."),
    ("E6", "E", "Code-gen", "Renumber stop_sequence on all trips to run 1,2,3... with no gaps, preserving order."),
    ("E7", "E", "Code-gen", "Duplicate the trip pattern of 78493439 as a new Saturday-only trip."),
    ("E8", "E", "Code-gen", "Reroute trip 76676011 to skip stop 'Massachusetts Ave @ Sidney St' and run directly between its neighbours."),

    # Group F - Under-specified Requests (leans Clarify)
    ("F1", "F", "Clarify", "Make the morning buses come more often."),
    ("F2", "F", "Clarify", "The weekend schedule looks wrong, can you fix it?"),
    ("F3", "F", "Clarify", "Add a stop near downtown."),
    ("F4", "F", "Clarify", "This trip is too slow, speed it up."),
    ("F5", "F", "Clarify", "Change the route colour to something nicer."),
    ("F6", "F", "Clarify", "Consolidate the stops that are too close together."),
]

SCENARIOS_BY_FEED = {
    "demo": DEMO_SCENARIOS,
    "mbta": MBTA_SCENARIOS,
}

# backward-compat default (used if a feed has no explicit binding)
SCENARIOS = DEMO_SCENARIOS
