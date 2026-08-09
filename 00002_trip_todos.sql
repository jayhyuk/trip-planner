-- Run after schema.sql against the existing travel planner database.
CREATE TABLE trip_todos (
    todo_id INTEGER PRIMARY KEY,
    trip_key TEXT NOT NULL,
    todo_name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'close')),
    FOREIGN KEY (trip_key) REFERENCES trips(trip_key) ON DELETE CASCADE
);

CREATE TABLE trip_todo_options (
    option_id INTEGER PRIMARY KEY,
    todo_id INTEGER NOT NULL,
    option_name TEXT NOT NULL,
    description TEXT,
    price REAL,
    detail_link TEXT,
    option_date TEXT,
    FOREIGN KEY (todo_id) REFERENCES trip_todos(todo_id) ON DELETE CASCADE,
    CHECK (option_date IS NULL OR date(option_date) IS NOT NULL),
    CHECK (price IS NULL OR price >= 0)
);

CREATE TABLE trip_todo_option_images (
    image_id INTEGER PRIMARY KEY,
    option_id INTEGER NOT NULL,
    image_url TEXT NOT NULL,
    FOREIGN KEY (option_id) REFERENCES trip_todo_options(option_id) ON DELETE CASCADE
);

CREATE INDEX idx_trip_todos_trip_key ON trip_todos (trip_key);
CREATE INDEX idx_trip_todo_options_todo_id ON trip_todo_options (todo_id);
CREATE INDEX idx_trip_todo_option_images_option_id ON trip_todo_option_images (option_id);
