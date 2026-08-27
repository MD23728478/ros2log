from flask import Blueprint, jsonify


blueprint = Blueprint("health", __name__)


@blueprint.get("/health")
def health():
    return jsonify(status="ok")
