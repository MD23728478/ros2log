from flask import jsonify

from backend.api import blueprint


@blueprint.get("/hello")
def hello():
    return jsonify(message="Hello from the API")
