"""Flask dashboard for XHS pipeline metrics."""

from pathlib import Path

from flask import Flask, render_template


def create_app() -> Flask:
    root = Path(__file__).resolve().parents[1]
    app = Flask(
        __name__,
        template_folder=str(root / "app" / "templates"),
        static_folder=str(root / "app" / "static"),
    )
    app.config["ROOT"] = root

    @app.route("/")
    def index():
        import json

        metrics_path = root / "data" / "processed" / "metrics.json"
        if not metrics_path.exists():
            metrics = {}
        else:
            metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
        return render_template("dashboard.html", metrics=metrics, root=root)

    return app
