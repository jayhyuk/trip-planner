"""Travel Planner JSON API server.

Run with: python3 app.py
"""

import json
import os
import sqlite3
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse


BASE_DIR = Path(__file__).resolve().parent
DATABASE_PATH = Path(os.environ.get("TRAVEL_PLANNER_DB", BASE_DIR / "db_file.sql"))
OPENAPI_PATH = BASE_DIR / "openapi.json"
SWAGGER_UI_PATH = BASE_DIR / "swagger.html"
VERCEL_FRONTEND_ORIGIN = "https://trip-planner-psi-ruby.vercel.app"

DETAIL_TABLES = {
    "travel_location": (
        "travel_locations",
        ("travel_location_name", "is_free", "ticket_purchased", "detail_link", "description"),
    ),
    "transportation": ("transportation", ("transportation_name", "is_booked")),
    "accommodation": ("accommodations", ("accommodation_name", "detail_link", "is_booked")),
}


class ApiError(Exception):
    """An error that can be returned as a JSON response."""

    def __init__(self, status, message):
        self.status = status
        self.message = message


def database_connection():
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def rows_as_dicts(rows):
    return [dict(row) for row in rows]


def require_fields(data, *field_names):
    missing = [name for name in field_names if data.get(name) in (None, "")]
    if missing:
        raise ApiError(HTTPStatus.BAD_REQUEST, f"Missing required field(s): {', '.join(missing)}")


def validate_date(value, field_name):
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except (TypeError, ValueError) as error:
        raise ApiError(HTTPStatus.BAD_REQUEST, f"{field_name} must use YYYY-MM-DD format") from error


def validate_time(value):
    for format_string in ("%H:%M", "%H:%M:%S"):
        try:
            datetime.strptime(value, format_string)
            return
        except (TypeError, ValueError):
            pass
    raise ApiError(HTTPStatus.BAD_REQUEST, "scheduled_time must use HH:MM or HH:MM:SS format")


def normalize_boolean(value, field_name):
    if isinstance(value, bool):
        return int(value)
    if value in (0, 1):
        return value
    raise ApiError(HTTPStatus.BAD_REQUEST, f"{field_name} must be true or false")


def validate_trip_data(data):
    require_fields(data, "trip_key", "trip_name", "start_date", "end_date")
    validate_date(data["start_date"], "start_date")
    validate_date(data["end_date"], "end_date")
    if data["start_date"] > data["end_date"]:
        raise ApiError(HTTPStatus.BAD_REQUEST, "start_date cannot be after end_date")


def detail_payload(data, schedule_type, is_new):
    table, fields = DETAIL_TABLES[schedule_type]
    result = {}
    if is_new:
        required = {
            "travel_location": ("travel_location_name", "is_free"),
            "transportation": ("transportation_name",),
            "accommodation": ("accommodation_name",),
        }
        require_fields(data, *required[schedule_type])

    for field in fields:
        if field in data:
            value = data[field]
            if field in ("is_free", "ticket_purchased", "is_booked"):
                value = normalize_boolean(value, field)
            result[field] = value

    if schedule_type == "travel_location":
        is_free = result.get("is_free")
        ticket_purchased = result.get("ticket_purchased")
        if is_free == 1 and ticket_purchased == 1:
            raise ApiError(HTTPStatus.BAD_REQUEST, "A free location cannot have a purchased ticket")
    return table, result


def serialize_schedule(connection, schedule):
    result = dict(schedule)
    table, fields = DETAIL_TABLES[result["schedule_type"]]
    detail = connection.execute(
        f"SELECT {', '.join(fields)} FROM {table} WHERE schedule_id = ?",
        (result["schedule_id"],),
    ).fetchone()
    if detail:
        result.update(dict(detail))
    for field in ("is_free", "ticket_purchased", "is_booked"):
        if field in result:
            result[field] = bool(result[field])
    return result


def schedule_by_id(connection, schedule_id):
    schedule = connection.execute(
        "SELECT schedule_id, trip_day_id, scheduled_time, schedule_type "
        "FROM schedules WHERE schedule_id = ?",
        (schedule_id,),
    ).fetchone()
    if schedule is None:
        raise ApiError(HTTPStatus.NOT_FOUND, "Schedule not found")
    return serialize_schedule(connection, schedule)


def validate_todo_status(status):
    if status not in ("open", "close"):
        raise ApiError(HTTPStatus.BAD_REQUEST, "status must be 'open' or 'close'")


def validate_option_data(data, is_new):
    if is_new:
        require_fields(data, "option_name")
    if "option_date" in data and data["option_date"] is not None:
        validate_date(data["option_date"], "option_date")
    if "price" in data and data["price"] is not None:
        if isinstance(data["price"], bool) or not isinstance(data["price"], (int, float)):
            raise ApiError(HTTPStatus.BAD_REQUEST, "price must be a number")
        if data["price"] < 0:
            raise ApiError(HTTPStatus.BAD_REQUEST, "price cannot be negative")
    if "image_urls" in data:
        image_urls = data["image_urls"]
        if not isinstance(image_urls, list) or any(not isinstance(url, str) or not url for url in image_urls):
            raise ApiError(HTTPStatus.BAD_REQUEST, "image_urls must be a list of non-empty URLs")


def option_by_id(connection, option_id):
    option = connection.execute(
        "SELECT option_id, todo_id, option_name, description, price, detail_link, option_date "
        "FROM trip_todo_options WHERE option_id = ?",
        (option_id,),
    ).fetchone()
    if option is None:
        raise ApiError(HTTPStatus.NOT_FOUND, "Todo option not found")
    result = dict(option)
    result["image_urls"] = [
        row["image_url"] for row in connection.execute(
            "SELECT image_url FROM trip_todo_option_images WHERE option_id = ? ORDER BY image_id",
            (option_id,),
        )
    ]
    return result


def todo_by_id(connection, todo_id, include_options=False):
    todo = connection.execute(
        "SELECT todo_id, trip_key, todo_name, status FROM trip_todos WHERE todo_id = ?",
        (todo_id,),
    ).fetchone()
    if todo is None:
        raise ApiError(HTTPStatus.NOT_FOUND, "Trip todo not found")
    result = dict(todo)
    if include_options:
        option_ids = connection.execute(
            "SELECT option_id FROM trip_todo_options WHERE todo_id = ? ORDER BY option_id",
            (todo_id,),
        )
        result["options"] = [option_by_id(connection, row["option_id"]) for row in option_ids]
    return result


class TravelPlannerHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format_string, *args):
        print(f"{self.address_string()} - {format_string % args}")

    def do_OPTIONS(self):
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_cors_headers()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        self.handle_request()

    def do_POST(self):
        self.handle_request()

    def do_PUT(self):
        self.handle_request()

    def do_DELETE(self):
        self.handle_request()

    def send_cors_headers(self):
        origin = self.headers.get("Origin")
        allowed_origin = VERCEL_FRONTEND_ORIGIN if origin == VERCEL_FRONTEND_ORIGIN else "*"
        self.send_header("Access-Control-Allow-Origin", allowed_origin)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def send_json(self, status, payload=None):
        body = b"" if payload is None else json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_cors_headers()
        if payload is not None:
            self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def send_html(self, status, body):
        encoded_body = body.encode("utf-8")
        self.send_response(status)
        self.send_cors_headers()
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded_body)))
        self.end_headers()
        self.wfile.write(encoded_body)

    def request_data(self):
        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length == 0:
            raise ApiError(HTTPStatus.BAD_REQUEST, "A JSON request body is required")
        try:
            data = json.loads(self.rfile.read(content_length))
        except json.JSONDecodeError as error:
            raise ApiError(HTTPStatus.BAD_REQUEST, "Request body must be valid JSON") from error
        if not isinstance(data, dict):
            raise ApiError(HTTPStatus.BAD_REQUEST, "JSON request body must be an object")
        return data

    def handle_request(self):
        try:
            path = [unquote(part) for part in urlparse(self.path).path.strip("/").split("/") if part]
            status, payload = self.route(path)
            if status is not None:
                self.send_json(status, payload)
        except ApiError as error:
            self.send_json(error.status, {"error": error.message})
        except sqlite3.IntegrityError as error:
            self.send_json(HTTPStatus.CONFLICT, {"error": str(error)})

    def route(self, path):
        if self.command == "GET" and path == ["health"]:
            return HTTPStatus.OK, {"status": "ok"}
        if self.command == "GET" and path == ["openapi.json"]:
            specification = json.loads(OPENAPI_PATH.read_text(encoding="utf-8"))
            host = self.headers.get("Host")
            if host:
                specification["servers"] = [
                    {
                        "url": f"http://{host}",
                        "description": "Current server",
                    }
                ]
            return HTTPStatus.OK, specification
        if self.command == "GET" and path == ["docs"]:
            self.send_html(HTTPStatus.OK, SWAGGER_UI_PATH.read_text(encoding="utf-8"))
            return None, None
        if not path or path[0] != "api":
            raise ApiError(HTTPStatus.NOT_FOUND, "Route not found")

        with database_connection() as connection:
            if path == ["api", "trips"]:
                if self.command == "GET":
                    trips = rows_as_dicts(connection.execute(
                        "SELECT trip_key, trip_name, start_date, end_date FROM trips ORDER BY start_date"
                    ))
                    return HTTPStatus.OK, trips
                if self.command == "POST":
                    data = self.request_data()
                    validate_trip_data(data)
                    connection.execute(
                        "INSERT INTO trips (trip_key, trip_name, start_date, end_date) VALUES (?, ?, ?, ?)",
                        (data["trip_key"], data["trip_name"], data["start_date"], data["end_date"]),
                    )
                    return HTTPStatus.CREATED, data

            if len(path) >= 3 and path[1] == "trips":
                trip_key = path[2]
                if len(path) == 3:
                    return self.trip_route(connection, trip_key)
                if len(path) == 4 and path[3] == "days":
                    return self.trip_days_route(connection, trip_key)
                if len(path) == 4 and path[3] == "todos":
                    return self.trip_todos_route(connection, trip_key)

            if len(path) == 4 and path[1] == "todos" and path[3] == "options":
                return self.todo_options_route(connection, self.integer_id(path[2], "todo"))

            if len(path) == 4 and path[1] == "todos" and path[3] == "compare":
                return self.todo_compare_route(connection, self.integer_id(path[2], "todo"))

            if len(path) == 3 and path[1] == "todos":
                return self.todo_route(connection, self.integer_id(path[2], "todo"))

            if len(path) == 3 and path[1] == "todo-options":
                return self.todo_option_route(connection, self.integer_id(path[2], "todo option"))

            if len(path) == 3 and path[1] == "days":
                return self.day_route(connection, self.integer_id(path[2], "trip day"))

            if len(path) == 4 and path[1] == "days" and path[3] == "schedules":
                return self.day_schedules_route(connection, self.integer_id(path[2], "trip day"))

            if len(path) == 3 and path[1] == "schedules":
                return self.schedule_route(connection, self.integer_id(path[2], "schedule"))

        raise ApiError(HTTPStatus.NOT_FOUND, "Route not found")

    @staticmethod
    def integer_id(value, resource_name):
        try:
            return int(value)
        except ValueError as error:
            raise ApiError(HTTPStatus.BAD_REQUEST, f"Invalid {resource_name} ID") from error

    def trip_route(self, connection, trip_key):
        trip = connection.execute(
            "SELECT trip_key, trip_name, start_date, end_date FROM trips WHERE trip_key = ?", (trip_key,)
        ).fetchone()
        if trip is None:
            raise ApiError(HTTPStatus.NOT_FOUND, "Trip not found")
        if self.command == "GET":
            return HTTPStatus.OK, dict(trip)
        if self.command == "PUT":
            data = self.request_data()
            validate_trip_data({**data, "trip_key": trip_key})
            outside_day = connection.execute(
                "SELECT 1 FROM trip_days WHERE trip_key = ? AND (day_date < ? OR day_date > ?)",
                (trip_key, data["start_date"], data["end_date"]),
            ).fetchone()
            if outside_day:
                raise ApiError(
                    HTTPStatus.BAD_REQUEST,
                    "Trip dates cannot exclude an existing trip day",
                )
            connection.execute(
                "UPDATE trips SET trip_name = ?, start_date = ?, end_date = ? WHERE trip_key = ?",
                (data["trip_name"], data["start_date"], data["end_date"], trip_key),
            )
            return HTTPStatus.OK, {**data, "trip_key": trip_key}
        if self.command == "DELETE":
            connection.execute("DELETE FROM trips WHERE trip_key = ?", (trip_key,))
            return HTTPStatus.NO_CONTENT, None
        raise ApiError(HTTPStatus.METHOD_NOT_ALLOWED, "Method not allowed")

    def trip_days_route(self, connection, trip_key):
        trip = connection.execute(
            "SELECT start_date, end_date FROM trips WHERE trip_key = ?", (trip_key,)
        ).fetchone()
        if trip is None:
            raise ApiError(HTTPStatus.NOT_FOUND, "Trip not found")
        if self.command == "GET":
            days = rows_as_dicts(connection.execute(
                "SELECT trip_day_id, trip_key, day_date FROM trip_days WHERE trip_key = ? ORDER BY day_date",
                (trip_key,),
            ))
            return HTTPStatus.OK, days
        if self.command == "POST":
            data = self.request_data()
            require_fields(data, "day_date")
            validate_date(data["day_date"], "day_date")
            if not trip["start_date"] <= data["day_date"] <= trip["end_date"]:
                raise ApiError(HTTPStatus.BAD_REQUEST, "day_date must be within the trip dates")
            cursor = connection.execute(
                "INSERT INTO trip_days (trip_key, day_date) VALUES (?, ?)", (trip_key, data["day_date"])
            )
            return HTTPStatus.CREATED, {
                "trip_day_id": cursor.lastrowid,
                "trip_key": trip_key,
                "day_date": data["day_date"],
            }
        raise ApiError(HTTPStatus.METHOD_NOT_ALLOWED, "Method not allowed")

    def day_route(self, connection, trip_day_id):
        day = connection.execute(
            "SELECT trip_day_id, trip_key, day_date FROM trip_days WHERE trip_day_id = ?", (trip_day_id,)
        ).fetchone()
        if day is None:
            raise ApiError(HTTPStatus.NOT_FOUND, "Trip day not found")
        if self.command == "PUT":
            data = self.request_data()
            require_fields(data, "day_date")
            validate_date(data["day_date"], "day_date")
            trip = connection.execute(
                "SELECT start_date, end_date FROM trips WHERE trip_key = ?", (day["trip_key"],)
            ).fetchone()
            if not trip["start_date"] <= data["day_date"] <= trip["end_date"]:
                raise ApiError(HTTPStatus.BAD_REQUEST, "day_date must be within the trip dates")
            connection.execute("UPDATE trip_days SET day_date = ? WHERE trip_day_id = ?", (data["day_date"], trip_day_id))
            return HTTPStatus.OK, {**dict(day), "day_date": data["day_date"]}
        if self.command == "DELETE":
            connection.execute("DELETE FROM trip_days WHERE trip_day_id = ?", (trip_day_id,))
            return HTTPStatus.NO_CONTENT, None
        raise ApiError(HTTPStatus.METHOD_NOT_ALLOWED, "Method not allowed")

    def day_schedules_route(self, connection, trip_day_id):
        day_exists = connection.execute("SELECT 1 FROM trip_days WHERE trip_day_id = ?", (trip_day_id,)).fetchone()
        if day_exists is None:
            raise ApiError(HTTPStatus.NOT_FOUND, "Trip day not found")
        if self.command == "GET":
            schedules = connection.execute(
                "SELECT schedule_id, trip_day_id, scheduled_time, schedule_type FROM schedules "
                "WHERE trip_day_id = ? ORDER BY scheduled_time, schedule_id",
                (trip_day_id,),
            ).fetchall()
            return HTTPStatus.OK, [serialize_schedule(connection, schedule) for schedule in schedules]
        if self.command == "POST":
            data = self.request_data()
            require_fields(data, "scheduled_time", "schedule_type")
            validate_time(data["scheduled_time"])
            if data["schedule_type"] not in DETAIL_TABLES:
                raise ApiError(HTTPStatus.BAD_REQUEST, "schedule_type is invalid")
            cursor = connection.execute(
                "INSERT INTO schedules (trip_day_id, scheduled_time, schedule_type) VALUES (?, ?, ?)",
                (trip_day_id, data["scheduled_time"], data["schedule_type"]),
            )
            schedule_id = cursor.lastrowid
            table, values = detail_payload(data, data["schedule_type"], is_new=True)
            columns = ["schedule_id", *values]
            connection.execute(
                f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
                (schedule_id, *values.values()),
            )
            return HTTPStatus.CREATED, schedule_by_id(connection, schedule_id)
        raise ApiError(HTTPStatus.METHOD_NOT_ALLOWED, "Method not allowed")

    def trip_todos_route(self, connection, trip_key):
        trip_exists = connection.execute("SELECT 1 FROM trips WHERE trip_key = ?", (trip_key,)).fetchone()
        if trip_exists is None:
            raise ApiError(HTTPStatus.NOT_FOUND, "Trip not found")
        if self.command == "GET":
            todos = connection.execute(
                "SELECT todo_id FROM trip_todos WHERE trip_key = ? ORDER BY todo_id",
                (trip_key,),
            )
            return HTTPStatus.OK, [todo_by_id(connection, row["todo_id"]) for row in todos]
        if self.command == "POST":
            data = self.request_data()
            require_fields(data, "todo_name")
            status = data.get("status", "open")
            validate_todo_status(status)
            cursor = connection.execute(
                "INSERT INTO trip_todos (trip_key, todo_name, status) VALUES (?, ?, ?)",
                (trip_key, data["todo_name"], status),
            )
            return HTTPStatus.CREATED, todo_by_id(connection, cursor.lastrowid)
        raise ApiError(HTTPStatus.METHOD_NOT_ALLOWED, "Method not allowed")

    def todo_route(self, connection, todo_id):
        if self.command == "GET":
            return HTTPStatus.OK, todo_by_id(connection, todo_id, include_options=True)
        current = todo_by_id(connection, todo_id)
        if self.command == "PUT":
            data = self.request_data()
            updates = {}
            if "todo_name" in data:
                if not data["todo_name"]:
                    raise ApiError(HTTPStatus.BAD_REQUEST, "todo_name cannot be empty")
                updates["todo_name"] = data["todo_name"]
            if "status" in data:
                validate_todo_status(data["status"])
                updates["status"] = data["status"]
            if not updates:
                raise ApiError(HTTPStatus.BAD_REQUEST, "Provide todo_name or status to update")
            assignments = ", ".join(f"{field} = ?" for field in updates)
            connection.execute(
                f"UPDATE trip_todos SET {assignments} WHERE todo_id = ?",
                (*updates.values(), todo_id),
            )
            return HTTPStatus.OK, todo_by_id(connection, todo_id)
        if self.command == "DELETE":
            connection.execute("DELETE FROM trip_todos WHERE todo_id = ?", (todo_id,))
            return HTTPStatus.NO_CONTENT, None
        raise ApiError(HTTPStatus.METHOD_NOT_ALLOWED, "Method not allowed")

    def todo_options_route(self, connection, todo_id):
        todo_by_id(connection, todo_id)
        if self.command == "GET":
            options = connection.execute(
                "SELECT option_id FROM trip_todo_options WHERE todo_id = ? ORDER BY option_id",
                (todo_id,),
            )
            return HTTPStatus.OK, [option_by_id(connection, row["option_id"]) for row in options]
        if self.command == "POST":
            data = self.request_data()
            validate_option_data(data, is_new=True)
            fields = ("option_name", "description", "price", "detail_link", "option_date")
            values = [data.get(field) for field in fields]
            cursor = connection.execute(
                "INSERT INTO trip_todo_options (todo_id, option_name, description, price, detail_link, option_date) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (todo_id, *values),
            )
            self.replace_option_images(connection, cursor.lastrowid, data.get("image_urls", []))
            return HTTPStatus.CREATED, option_by_id(connection, cursor.lastrowid)
        raise ApiError(HTTPStatus.METHOD_NOT_ALLOWED, "Method not allowed")

    def todo_option_route(self, connection, option_id):
        current = option_by_id(connection, option_id)
        if self.command == "GET":
            return HTTPStatus.OK, current
        if self.command == "PUT":
            data = self.request_data()
            validate_option_data(data, is_new=False)
            allowed_fields = ("option_name", "description", "price", "detail_link", "option_date")
            updates = {field: data[field] for field in allowed_fields if field in data}
            if "option_name" in updates and not updates["option_name"]:
                raise ApiError(HTTPStatus.BAD_REQUEST, "option_name cannot be empty")
            if not updates and "image_urls" not in data:
                raise ApiError(HTTPStatus.BAD_REQUEST, "Provide an option field or image_urls to update")
            if updates:
                assignments = ", ".join(f"{field} = ?" for field in updates)
                connection.execute(
                    f"UPDATE trip_todo_options SET {assignments} WHERE option_id = ?",
                    (*updates.values(), option_id),
                )
            if "image_urls" in data:
                self.replace_option_images(connection, option_id, data["image_urls"])
            return HTTPStatus.OK, option_by_id(connection, option_id)
        if self.command == "DELETE":
            connection.execute("DELETE FROM trip_todo_options WHERE option_id = ?", (option_id,))
            return HTTPStatus.NO_CONTENT, None
        raise ApiError(HTTPStatus.METHOD_NOT_ALLOWED, "Method not allowed")

    def todo_compare_route(self, connection, todo_id):
        todo = todo_by_id(connection, todo_id)
        options = connection.execute(
            "SELECT option_id FROM trip_todo_options WHERE todo_id = ? ORDER BY option_id",
            (todo_id,),
        )
        return HTTPStatus.OK, {
            "todo": todo,
            "columns": ["option_name", "description", "price", "detail_link", "option_date", "image_urls"],
            "options": [option_by_id(connection, row["option_id"]) for row in options],
        }

    @staticmethod
    def replace_option_images(connection, option_id, image_urls):
        connection.execute("DELETE FROM trip_todo_option_images WHERE option_id = ?", (option_id,))
        connection.executemany(
            "INSERT INTO trip_todo_option_images (option_id, image_url) VALUES (?, ?)",
            [(option_id, image_url) for image_url in image_urls],
        )

    def schedule_route(self, connection, schedule_id):
        current = schedule_by_id(connection, schedule_id)
        if self.command == "GET":
            return HTTPStatus.OK, current
        if self.command == "PUT":
            data = self.request_data()
            if "schedule_type" in data and data["schedule_type"] != current["schedule_type"]:
                raise ApiError(HTTPStatus.BAD_REQUEST, "schedule_type cannot be changed")
            if "scheduled_time" in data:
                validate_time(data["scheduled_time"])
                connection.execute(
                    "UPDATE schedules SET scheduled_time = ? WHERE schedule_id = ?",
                    (data["scheduled_time"], schedule_id),
                )
            table, values = detail_payload(
                {**current, **data},
                current["schedule_type"],
                is_new=False,
            )
            if values:
                assignments = ", ".join(f"{field} = ?" for field in values)
                connection.execute(
                    f"UPDATE {table} SET {assignments} WHERE schedule_id = ?",
                    (*values.values(), schedule_id),
                )
            return HTTPStatus.OK, schedule_by_id(connection, schedule_id)
        if self.command == "DELETE":
            connection.execute("DELETE FROM schedules WHERE schedule_id = ?", (schedule_id,))
            return HTTPStatus.NO_CONTENT, None
        raise ApiError(HTTPStatus.METHOD_NOT_ALLOWED, "Method not allowed")


def main():
    host = os.environ.get("TRAVEL_PLANNER_HOST", "0.0.0.0")
    port = int(os.environ.get("TRAVEL_PLANNER_PORT", "9189"))
    server = ThreadingHTTPServer((host, port), TravelPlannerHandler)
    print(f"Travel Planner API listening on http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
