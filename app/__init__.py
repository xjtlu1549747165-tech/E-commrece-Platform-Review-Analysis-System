"""Flask dashboard for XHS pipeline metrics."""

import json
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, abort, jsonify, render_template, request, url_for

from app.job_runner import (
    check_chromium,
    discover_tracks,
    get_active_job,
    poll_job,
    start_job,
)
from app.policy_registry import REGION_DOCUMENTS, REGION_LABEL_EN

try:
    import markdown
except ImportError:
    markdown = None  # type: ignore


def create_app() -> Flask:
    root = Path(__file__).resolve().parents[1]
    app = Flask(
        __name__,
        template_folder=str(root / "app" / "templates"),
        static_folder=str(root / "app" / "static"),
    )
    app.config["ROOT"] = root

    def load_metrics() -> dict:
        metrics_path = root / "data" / "processed" / "metrics.json"
        if not metrics_path.exists():
            return {}
        return json.loads(metrics_path.read_text(encoding="utf-8"))

    def track_keys_from_metrics(metrics: dict) -> list[str]:
        return list(metrics.keys())

    def load_brief_index() -> dict:
        p = root / "docs" / "briefs" / "index.json"
        if not p.exists():
            return {"briefs": []}
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {"briefs": []}

    def render_markdown(md_text: str) -> str:
        if not markdown:
            return "<p><em>Install the <code>markdown</code> package to render briefs.</em></p>"
        return markdown.markdown(
            md_text,
            extensions=["fenced_code", "tables", "nl2br"],
        )

    @app.route("/")
    def index():
        metrics = load_metrics()
        track_keys = track_keys_from_metrics(metrics)
        return render_template(
            "overview.html",
            metrics=metrics,
            track_keys=track_keys,
            active_nav="overview",
        )

    @app.route("/figures")
    def figures():
        metrics = load_metrics()
        track_keys = track_keys_from_metrics(metrics)
        return render_template(
            "figures.html",
            metrics=metrics,
            track_keys=track_keys,
            active_nav="figures",
        )

    @app.route("/brief")
    def brief_index():
        index_data = load_brief_index()
        briefs = index_data.get("briefs", [])
        return render_template(
            "brief.html",
            briefs=briefs,
            current_id=None,
            body_html=None,
            active_nav="brief",
        )

    @app.route("/brief/<brief_id>")
    def brief_view(brief_id: str):
        index_data = load_brief_index()
        briefs = index_data.get("briefs", [])
        entry = next((b for b in briefs if b.get("id") == brief_id), None)
        if not entry:
            abort(404)
        body_html = None
        fname = entry.get("filename") or f"brief_{brief_id}.md"
        md_path = root / "docs" / "briefs" / fname
        if md_path.is_file():
            raw = md_path.read_text(encoding="utf-8")
            body_html = render_markdown(raw)
        return render_template(
            "brief.html",
            briefs=briefs,
            current_id=brief_id,
            body_html=body_html,
            active_nav="brief",
        )

    @app.route("/pipeline")
    def pipeline_page():
        return render_template("pipeline.html", active_nav="pipeline")

    @app.route("/api/pipeline/tracks")
    def api_pipeline_tracks():
        return jsonify({"tracks": discover_tracks()})

    @app.route("/api/pipeline/chromium-status")
    def api_chromium_status():
        return jsonify(check_chromium())

    @app.route("/api/jobs/active")
    def api_jobs_active():
        job = get_active_job()
        if not job:
            return jsonify({"active": None})
        return jsonify({"active": poll_job(job["job_id"])})

    @app.route("/api/jobs", methods=["POST"])
    def api_jobs_create():
        body = request.get_json(silent=True) or {}
        job_type = (body.get("type") or "").strip().lower()
        if not job_type:
            return jsonify({"error": "Missing job type"}), 400
        params: dict = {}
        if job_type in ("crawl", "enrich", "nlp"):
            track = (body.get("track") or "").strip()
            if not track:
                return jsonify({"error": "Missing track"}), 400
            params["track"] = track
        if job_type == "enrich" and body.get("limit") is not None:
            try:
                params["limit"] = int(body["limit"])
            except (TypeError, ValueError):
                return jsonify({"error": "Invalid limit"}), 400
        if job_type == "nlp":
            params["track"] = (body.get("track") or "all").strip().lower()
        if job_type == "brief":
            tracks = body.get("tracks") or []
            if not isinstance(tracks, list) or not tracks:
                return jsonify({"error": "Select at least one track for brief"}), 400
            params["tracks"] = [str(t).strip() for t in tracks if str(t).strip()]
        try:
            status = start_job(job_type, params)
            return jsonify(status), 201
        except FileNotFoundError as e:
            return jsonify({"error": str(e)}), 400
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        except RuntimeError as e:
            return jsonify({"error": str(e)}), 409

    @app.route("/api/jobs/<job_id>")
    def api_jobs_poll(job_id: str):
        status = poll_job(job_id)
        if not status:
            return jsonify({"error": "Job not found"}), 404
        return jsonify(status)

    @app.route("/policy")
    def policy_page():
        last_loaded = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        documents_by_region: dict = {}
        for code, items in REGION_DOCUMENTS.items():
            documents_by_region[code] = []
            for item in items:
                row = dict(item)
                row["pdf_url"] = url_for(
                    "static",
                    filename=f"policy/{code}/{item['filename']}",
                )
                documents_by_region[code].append(row)
        hk_docs = documents_by_region.get("HK", [])
        return render_template(
            "policy.html",
            active_nav="policy",
            last_loaded_utc=last_loaded,
            hk_docs=hk_docs,
            region_label_hk=REGION_LABEL_EN.get("HK", "Hong Kong SAR"),
        )

    return app
