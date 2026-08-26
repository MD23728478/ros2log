from flask import Blueprint, render_template


blueprint = Blueprint("pages", __name__)


@blueprint.get("/")
def index():
    return render_template("index.html", name="World")
