from datetime import datetime, timezone
from pathlib import Path

from flask import jsonify

from backend.api import blueprint
from runner.client import RunnerMetricsError, runner_metrics
from runner.metrics import MetricsError, collect_metrics


@blueprint.get("/performance")
def performance():
    """Return live resource snapshots for the app and ROS runner environments."""
    targets = {}

    try:
        targets["application"] = {"status": "ok", "metrics": collect_metrics(storage_path=Path("/"))}
    except MetricsError as error:
        targets["application"] = {"status": "error", "error": str(error)}

    try:
        targets["runner"] = {"status": "ok", "metrics": runner_metrics()}
    except RunnerMetricsError as error:
        targets["runner"] = {"status": "error", "error": str(error)}

    status = 200 if any(target["status"] == "ok" for target in targets.values()) else 503
    response = jsonify(
        sampled_at=datetime.now(timezone.utc).isoformat(),
        targets=targets,
    )
    response.headers["Cache-Control"] = "no-store"
    return response, status
