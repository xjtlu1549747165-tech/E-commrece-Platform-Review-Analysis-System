"""
Generate a short English strategic brief from data/processed/metrics.json via LLM API.

Requires OPENAI_API_KEY and optional OPENAI_API_BASE / OPENAI_MODEL in .env.

Usage:
  python scripts/generate_brief.py
  python scripts/generate_brief.py --out docs/strategic_brief.md
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]


def load_metrics() -> dict:
    p = ROOT / "data" / "processed" / "metrics.json"
    if not p.exists():
        print("Run: python -m src.nlp.process", file=sys.stderr)
        sys.exit(1)
    return json.loads(p.read_text(encoding="utf-8"))


def build_prompt(metrics: dict) -> str:
    payload = json.dumps(metrics, ensure_ascii=False, indent=2)
    return f"""You are an analyst helping Master Mock EduTech (Hong Kong) assess mainland China market entry for AI-assisted DSE preparation tools.

Below is aggregated public-data analytics from Xiaohongshu (two tracks: DSE exam discussion vs IELTS AI prep products as a comparable "AI-assisted exam prep" segment). Text mining uses post titles, bodies (after enrichment), and public comment text where scraped; comment counts are in the JSON. No personal data is included.

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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=ROOT / "docs" / "strategic_brief.md")
    args = parser.parse_args()
    metrics = load_metrics()
    prompt = build_prompt(metrics)
    text = call_llm(prompt)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    header = "# AI-assisted exam prep — strategic brief (draft)\n\n_Generated from aggregated metrics; not legal or investment advice._\n\n"
    args.out.write_text(header + text, encoding="utf-8")
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
