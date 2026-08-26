import sqlite3
from pathlib import Path

from flask import current_app, g


SCHEMA_FILE = Path(__file__).with_name("schema.sql")


def connect() -> sqlite3.Connection:
    database = current_app.config["DATABASE"]
    connection = sqlite3.connect(database, uri=database.startswith("file:"))
    connection.row_factory = sqlite3.Row
    return connection


def get_database() -> sqlite3.Connection:
    if "database" not in g:
        g.database = connect()
    return g.database


def close_database(_error=None) -> None:
    database = g.pop("database", None)
    if database is not None:
        database.close()


def init_app(app) -> None:
    app.teardown_appcontext(close_database)

    with app.app_context():
        database = connect()
        database.executescript(SCHEMA_FILE.read_text())
        database.commit()

        if app.config["PERSIST_DATABASE"]:
            database.close()
        else:
            app.extensions["database_keeper"] = database
