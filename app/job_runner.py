"""Background pipeline jobs via subprocess (single active job globally)."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from crawler.xhs_crawler import discover_tracks, validate_track

ROOT = Path(__file__).resolve().parents[1]
JOBS_DIR = ROOT / "data" / "jobs"
ACTIVE_PATH = JOBS_DIR / "_active.json"
BRIEF_INDEX = ROOT / "docs" / "briefs" / "index.json"
LOG_TAIL_LINES = 200

_JOB_LOCK = threading.Lock()


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def chromium_address() -> str:
    load_dotenv(ROOT / ".env")
    return os.environ.get("CHROMIUM_ADDRESS", "127.0.0.1:9527").strip()


def check_chromium(address: str | None = None) -> dict[str, Any]:
    addr = address or chromium_address()
    host, _, port_s = addr.partition(":")
    if not host or not port_s:
        return {"address": addr, "reachable": False, "error": "invalid address"}
    try:
        port = int(port_s)
    except ValueError:
        return {"address": addr, "reachable": False, "error": "invalid port"}
    try:
        with socket.create_connection((host, port), timeout=2.0):
            return {"address": addr, "reachable": True}
    except OSError as e:
        return {"address": addr, "reachable": False, "error": str(e)}


def get_active_job() -> dict[str, Any] | None:
    active = _read_json(ACTIVE_PATH)
    job_id = active.get("job_id")
    if not job_id:
        return None
    status = _read_json(JOBS_DIR / job_id / "status.json")
    if status.get("status") == "running":
        return status
    return None


def _build_command(job_type: str, params: dict[str, Any]) -> list[str]:
    exe = sys.executable
    if job_type == "crawl":
        track = validate_track(params["track"])
        return [exe, "-m", "crawler.xhs_crawler", "--track", track]
    if job_type == "enrich":
        track = validate_track(params["track"])
        cmd = [exe, "-m", "crawler.xhs_enrich", "--track", track]
        limit = params.get("limit")
        if limit is not None and int(limit) > 0:
            cmd.extend(["--limit", str(int(limit))])
        return cmd
    if job_type == "nlp":
        track = (params.get("track") or "all").strip().lower()
        if track != "all":
            validate_track(track)
        return [exe, "-m", "src.nlp.process", "--track", track]
    if job_type == "brief":
        tracks = params.get("tracks") or []
        if not tracks:
            raise ValueError("At least one track required for brief generation.")
        validated = [validate_track(t) for t in tracks]
        cmd = [exe, str(ROOT / "scripts" / "generate_brief.py"), "--tracks", *validated]
        return cmd
    raise ValueError(f"Unknown job type: {job_type}")


def _latest_brief_id() -> str | None:
    data = _read_json(BRIEF_INDEX)
    briefs = data.get("briefs") or []
    if briefs and isinstance(briefs[0], dict):
        return briefs[0].get("id")
    return None


def _wait_process(
    job_id: str, proc: subprocess.Popen, job_type: str, log_file: Any | None
) -> None:
    job_dir = JOBS_DIR / job_id
    status_path = job_dir / "status.json"
    log_path = job_dir / "log.txt"
    exit_code = proc.wait()
    if log_file is not None:
        try:
            log_file.close()
        except Exception:
            pass
    status = _read_json(status_path)
    status["finished_at"] = _utc_now()
    status["exit_code"] = exit_code
    if exit_code == 0:
        status["status"] = "success"
        result: dict[str, Any] = {}
        if job_type == "brief":
            bid = _latest_brief_id()
            if bid:
                result["brief_id"] = bid
        status["result"] = result
    else:
        status["status"] = "failed"
        try:
            tail = log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-20:]
            status["error"] = "\n".join(tail) if tail else f"Process exited with code {exit_code}"
        except OSError:
            status["error"] = f"Process exited with code {exit_code}"
    _write_json(status_path, status)
    if ACTIVE_PATH.is_file():
        active = _read_json(ACTIVE_PATH)
        if active.get("job_id") == job_id:
            ACTIVE_PATH.unlink(missing_ok=True)


def start_job(job_type: str, params: dict[str, Any]) -> dict[str, Any]:
    job_type = job_type.strip().lower()
    if job_type not in ("crawl", "enrich", "nlp", "brief"):
        raise ValueError(f"Invalid job type: {job_type}")

    with _JOB_LOCK:
        if get_active_job():
            raise RuntimeError("Another job is already running.")

        if job_type in ("crawl", "enrich"):
            chrome = check_chromium()
            if not chrome.get("reachable"):
                raise RuntimeError(
                    f"Chromium debugger not reachable at {chrome.get('address')}. "
                    "Start Chrome with remote debugging and log in to Xiaohongshu."
                )

        cmd = _build_command(job_type, params)
        job_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "_" + uuid.uuid4().hex[:8]
        job_dir = JOBS_DIR / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        log_path = job_dir / "log.txt"

        status: dict[str, Any] = {
            "job_id": job_id,
            "type": job_type,
            "params": params,
            "status": "running",
            "started_at": _utc_now(),
            "command": cmd,
        }
        _write_json(job_dir / "status.json", status)
        _write_json(ACTIVE_PATH, {"job_id": job_id})

        env = os.environ.copy()
        env.setdefault("PYTHONPATH", str(ROOT))
        log_f = open(log_path, "a", encoding="utf-8")
        log_f.write(f"[{_utc_now()}] Starting: {' '.join(cmd)}\n\n")
        log_f.flush()
        proc = subprocess.Popen(
            cmd,
            cwd=str(ROOT),
            stdout=log_f,
            stderr=subprocess.STDOUT,
            env=env,
        )

        t = threading.Thread(
            target=_wait_process, args=(job_id, proc, job_type, log_f), daemon=True
        )
        t.start()
        return status


def poll_job(job_id: str) -> dict[str, Any] | None:
    status_path = JOBS_DIR / job_id / "status.json"
    if not status_path.is_file():
        return None
    status = _read_json(status_path)
    log_path = JOBS_DIR / job_id / "log.txt"
    if log_path.is_file():
        try:
            lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
            status["log_tail"] = "\n".join(lines[-LOG_TAIL_LINES:])
        except OSError:
            status["log_tail"] = ""
    else:
        status["log_tail"] = ""
    return status
