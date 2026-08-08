-- Run this file against a SQLite database to create the travel planner schema.
PRAGMA foreign_keys = ON;

CREATE TABLE trips (
    trip_key TEXT PRIMARY KEY,
    trip_name TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    CHECK (date(start_date) IS NOT NULL),
    CHECK (date(end_date) IS NOT NULL),
    CHECK (start_date <= end_date)
);

CREATE TABLE trip_days (
    trip_day_id INTEGER PRIMARY KEY,
    trip_key TEXT NOT NULL,
    day_date TEXT NOT NULL,
    FOREIGN KEY (trip_key) REFERENCES trips(trip_key) ON DELETE CASCADE,
    UNIQUE (trip_key, day_date),
    CHECK (date(day_date) IS NOT NULL)
);

CREATE TABLE schedules (
    schedule_id INTEGER PRIMARY KEY,
    trip_day_id INTEGER NOT NULL,
    scheduled_time TEXT NOT NULL,
    schedule_type TEXT NOT NULL CHECK (
        schedule_type IN ('travel_location', 'transportation', 'accommodation')
    ),
    FOREIGN KEY (trip_day_id) REFERENCES trip_days(trip_day_id) ON DELETE CASCADE,
    CHECK (time(scheduled_time) IS NOT NULL)
);

CREATE TABLE travel_locations (
    schedule_id INTEGER PRIMARY KEY,
    travel_location_name TEXT NOT NULL,
    is_free INTEGER NOT NULL CHECK (is_free IN (0, 1)),
    ticket_purchased INTEGER NOT NULL DEFAULT 0 CHECK (ticket_purchased IN (0, 1)),
    detail_link TEXT,
    description TEXT,
    FOREIGN KEY (schedule_id) REFERENCES schedules(schedule_id) ON DELETE CASCADE,
    CHECK (is_free = 0 OR ticket_purchased = 0)
);

CREATE TABLE transportation (
    schedule_id INTEGER PRIMARY KEY,
    transportation_name TEXT NOT NULL,
    is_booked INTEGER NOT NULL DEFAULT 0 CHECK (is_booked IN (0, 1)),
    FOREIGN KEY (schedule_id) REFERENCES schedules(schedule_id) ON DELETE CASCADE
);

CREATE TABLE accommodations (
    schedule_id INTEGER PRIMARY KEY,
    accommodation_name TEXT NOT NULL,
    detail_link TEXT,
    is_booked INTEGER NOT NULL DEFAULT 0 CHECK (is_booked IN (0, 1)),
    FOREIGN KEY (schedule_id) REFERENCES schedules(schedule_id) ON DELETE CASCADE
);

CREATE INDEX idx_trip_days_trip_key ON trip_days (trip_key);
CREATE INDEX idx_schedules_day_time ON schedules (trip_day_id, scheduled_time);
