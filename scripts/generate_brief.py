"""
Generate a short English strategic brief from data/processed/metrics.json via LLM API.

Requires OPENAI_API_KEY and optional OPENAI_API_BASE / OPENAI_MODEL in .env.

Usage:
  python scripts/generate_brief.py --tracks dse ielts_ai
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
BRIEFS_DIR = ROOT / "docs" / "briefs"
INDEX_PATH = BRIEFS_DIR / "index.json"


def load_metrics() -> dict:
    p = ROOT / "data" / "processed" / "metrics.json"
    if not p.exists():
        print("Run: python -m src.nlp.process", file=sys.stderr)
        sys.exit(1)
    return json.loads(p.read_text(encoding="utf-8"))


def filter_metrics(metrics: dict, tracks: list[str]) -> dict:
    out: dict = {}
    missing: list[str] = []
    for t in tracks:
        if t not in metrics:
            missing.append(t)
            continue
        block = metrics[t]
        if block.get("error"):
            print(f"Track {t!r} has error in metrics: {block.get('error')}", file=sys.stderr)
            sys.exit(1)
        out[t] = block
    if missing:
        print(f"Unknown track(s) in metrics.json: {missing}", file=sys.stderr)
        sys.exit(1)
    return out


def build_prompt(metrics_subset: dict, track_list: list[str]) -> str:
    payload = json.dumps(metrics_subset, ensure_ascii=False, indent=2)
    n = len(track_list)
    names = ", ".join(track_list)
    return f"""You are an analyst helping Master Mock EduTech (Hong Kong) assess mainland China market entry for AI-assisted DSE preparation tools.

Below is aggregated public-data analytics from Xiaohongshu for {n} track(s): {names}. Each key in the JSON is one track. Text mining uses post titles, bodies (after enrichment), and public comment text where scraped; engagement fields informed a weighted sentiment summary in the JSON. No personal data is included.

Data (JSON):
{payload}

Write a concise strategic brief in English with these sections:
1) Executive summary (5-8 bullet points max)
2) Observed trends (platform narratives, anxiety vs interest signals)
3) Risks and limitations (data bias, sample size, compliance)
4) Recommendations for next validation steps before a Go/No-Go decision

Keep total length under 700 words. Be careful not to over-claim causality."""


def call_llm(prompt: str) -> str:
    load_dotenv(ROOT / ".env")
    key = os.environ.get("OPENAI_API_KEY")
    base = os.environ.get("OPENAI_API_BASE", "https://api.openai.com/v1").rstrip("/")
    model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    if not key:
        print("Set OPENAI_API_KEY in .env", file=sys.stderr)
        sys.exit(1)
    url = f"{base}/chat/completions"
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 1200,
        "temperature": 0.4,
    }
    r = httpx.post(
        url,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json=body,
        timeout=120.0,
    )
    r.raise_for_status()
    data = r.json()
    return data["choices"][0]["message"]["content"]


def valid_notes_total(metrics_subset: dict) -> int:
    return int(sum(int(v.get("valid_count") or 0) for v in metrics_subset.values()))


def append_index(entry: dict) -> None:
    BRIEFS_DIR.mkdir(parents=True, exist_ok=True)
    if INDEX_PATH.exists():
        try:
            data = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = {"briefs": []}
    else:
        data = {"briefs": []}
    briefs = data.setdefault("briefs", [])
    briefs.insert(0, entry)
    INDEX_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate strategic brief from metrics (append-only under docs/briefs/).")
    parser.add_argument(
        "--tracks",
        nargs="+",
        required=True,
        metavar="TRACK",
        help="One or more track ids (keys in metrics.json), e.g. dse ielts_ai",
    )
    args = parser.parse_args()
    tracks = list(dict.fromkeys(args.tracks))

    metrics = load_metrics()
    subset = filter_metrics(metrics, tracks)
    prompt = build_prompt(subset, tracks)
    text = call_llm(prompt)

    now = datetime.now(timezone.utc)
    brief_id = now.strftime("%Y%m%dT%H%M%SZ")
    created_utc = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    fname = f"brief_{brief_id}.md"
    out_md = BRIEFS_DIR / fname

    BRIEFS_DIR.mkdir(parents=True, exist_ok=True)
    header = (
        "# AI-assisted exam prep — strategic brief (draft)\n\n"
        f"_Generated at {created_utc} (UTC) from tracks: {', '.join(tracks)}; "
        f"valid notes used: {valid_notes_total(subset)}._\n\n"
        "_Not legal or investment advice._\n\n"
    )
    out_md.write_text(header + text, encoding="utf-8")

    append_index(
        {
            "id": brief_id,
            "created_utc": created_utc,
            "tracks": tracks,
            "valid_notes_total": valid_notes_total(subset),
            "filename": fname,
        }
    )
    print(f"Wrote {out_md}")
    print(f"Updated {INDEX_PATH}")


if __name__ == "__main__":
    main()
