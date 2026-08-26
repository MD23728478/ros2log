from flask import Blueprint


blueprint = Blueprint("api", __name__)

from backend.api import hello  # noqa: E402, F401
