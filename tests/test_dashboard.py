import json
import re
from pathlib import Path

from docmind_service.metrics import render_metrics

# Helper to find metric names in a dashboard JSON file


def collect_metric_names_from_dashboard(path: Path) -> set[str]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    names = set()
    for panel in data.get("panels", []):
        for target in panel.get("targets", []):
            expr = target.get("expr", "")
            for m in re.findall(r"\b[\w_]+\b", expr):
                if m.startswith("docmind_") or m.startswith("process_"):
                    names.add(m)
    return names


def test_dashboard_metric_drift_and_panels(tmp_path):
    # Render metrics from a fresh app (no DB). 100 requests.
    from fastapi.testclient import TestClient

    from docmind_service.config import Settings
    from docmind_service.main import create_app

    app = create_app(settings=Settings(_env_file=None))
    client = TestClient(app)
    for _ in range(100):
        client.get("/healthz")
    text = render_metrics(None).decode()

    # Load dashboard
    dash_path = Path("deploy/observability/grafana/dashboards/docmind.json")
    metrics_in_dash = collect_metric_names_from_dashboard(dash_path)
    assert len(dash_path.read_text()) > 0
    assert len(metrics_in_dash) >= 10

    # Check each metric exists in the exposition. process_* metrics come
    # from the Prometheus process collector, which reads /proc and is a
    # no-op where /proc does not exist (e.g. Windows) - check those only
    # where the collector can actually emit them.
    has_proc = Path("/proc/self").exists()
    for name in metrics_in_dash:
        if name.startswith("process_") and not has_proc:
            continue
        assert name in text, f"metric {name} missing"

    # Panels count
    with dash_path.open("r", encoding="utf-8") as f:
        dash = json.load(f)
    assert len(dash.get("panels", [])) >= 10


def test_metrics_excluded_from_openapi(tmp_path):
    # The /metrics route is hand-written with include_in_schema=False.
    # The property that matters is behavioral: /metrics must not appear
    # in the served OpenAPI schema.
    from fastapi.testclient import TestClient

    from docmind_service.config import Settings
    from docmind_service.main import create_app

    app = create_app(settings=Settings(_env_file=None))
    client = TestClient(app)
    response = client.get("/openapi.json")
    assert response.status_code == 200
    assert "/metrics" not in response.json().get("paths", {})
