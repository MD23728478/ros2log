from pathlib import Path

from flask import Flask

from backend.api import blueprint as api_blueprint
from backend.database import init_app as init_database
from backend.health import blueprint as health_blueprint
from backend.pages import blueprint as pages_blueprint


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def create_app() -> Flask:
    app = Flask(
        __name__,
        template_folder=PROJECT_ROOT / "frontend" / "templates",
        static_folder=PROJECT_ROOT / "frontend" / "static",
    )
    app.config.from_object("config")
    app.logger.setLevel(app.config["LOG_LEVEL"])
    app.logger.disabled = not app.config["LOGGING_ENABLED"]

    init_database(app)
    app.register_blueprint(pages_blueprint)
    app.register_blueprint(health_blueprint)
    app.register_blueprint(api_blueprint, url_prefix="/api")

    return app
