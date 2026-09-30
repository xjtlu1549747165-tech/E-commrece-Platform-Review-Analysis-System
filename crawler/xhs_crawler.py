"""
Xiaohongshu search crawler using DrissionPage + intercepted search/notes API.

Requires a running Chromium with remote debugging (see CHROMIUM_ADDRESS in .env).
User may need to log in to xiaohongshu.com in that browser once.

Usage:
  python -m crawler.xhs_crawler --track dse
  python -m crawler.xhs_crawler --track ielts_ai
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import random
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode

import yaml
from DrissionPage import ChromiumPage

# Project root
ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
CONFIG_DIR = ROOT / "config"

SEARCH_NOTES_SUBSTR = "search/notes"
XHS_SEARCH_BASE = "https://www.xiaohongshu.com/search_result"
# Query params for explore URLs from search/notes items (see Network Preview: item.xsec_token).
EXPLORE_Q_XSEC_SOURCE = "pc_search"
EXPLORE_Q_SOURCE = "web_search_result_notes"


def build_explore_url(note_id: str, item: dict[str, Any]) -> str:
    """
    Web 版笔记详情通常需要 xsec_token，否则 /explore/{id} 可能 404。
    Token 在 search/notes 的每条 item 上与 note_card 同级（或偶见嵌于 note_card）。
    """
    base = f"https://www.xiaohongshu.com/explore/{note_id}"
    token = item.get("xsec_token")
    if token is None and isinstance(item.get("note_card"), dict):
        token = item["note_card"].get("xsec_token")
    if not token:
        return base
    token = str(token).strip()
    if not token:
        return base
    q = {
        "xsec_token": token,
        "xsec_source": EXPLORE_Q_XSEC_SOURCE,
        "source": EXPLORE_Q_SOURCE,
    }
    return f"{base}?{urlencode(q)}"


TRACK_ID_RE = re.compile(r"^[a-z0-9_]+$")


def validate_track(track: str) -> str:
    """Return normalized track id or raise ValueError."""
    t = (track or "").strip().lower()
    if not t or not TRACK_ID_RE.match(t):
        raise ValueError(
            f"Invalid track {track!r}: use lowercase letters, digits, underscores only."
        )
    path = CONFIG_DIR / f"{t}_keywords.yaml"
    if not path.is_file():
        raise FileNotFoundError(f"Missing keyword config: {path}")
    return t


def discover_tracks() -> list[str]:
    names: list[str] = []
    for p in sorted(CONFIG_DIR.glob("*_keywords.yaml")):
        stem = p.stem
        if stem.endswith("_keywords"):
            names.append(stem[: -len("_keywords")])
    return names


def load_config(track: str) -> dict[str, Any]:
    t = validate_track(track)
    path = CONFIG_DIR / f"{t}_keywords.yaml"
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def mask_author(nick: str | None) -> str:
    if not nick:
        return ""
    h = hashlib.sha256(nick.encode("utf-8")).hexdigest()
    return f"u_{h[:10]}"


def api_data_dict(body: Any) -> dict[str, Any]:
    """
    Safe access to JSON `data` for Xiaohongshu APIs.
    `data` is sometimes a string (error message) or other non-dict; `x or {}` would keep the string and break `.get()`.
    """
    if not isinstance(body, dict):
        return {}
    d = body.get("data")
    return d if isinstance(d, dict) else {}


def api_search_payload(body: dict[str, Any]) -> dict[str, Any]:
    """Prefer nested `data` when it is a dict; else use top-level body for items/notes."""
    inner = body.get("data")
    if isinstance(inner, dict):
        return inner
    return body


def parse_interact_count(val: Any) -> int | None:
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return int(val)
    s = str(val).strip().replace(",", "")
    if not s:
        return None
    m = re.match(r"^([\d.]+)\s*万", s)
    if m:
        return int(float(m.group(1)) * 10000)
    m = re.match(r"^([\d.]+)\s*千", s)
    if m:
        return int(float(m.group(1)) * 1000)
    m = re.search(r"(\d+)", s)
    if m:
        return int(m.group(1))
    return None


def extract_note_from_item(item: dict[str, Any]) -> dict[str, Any] | None:
    if not item or not isinstance(item, dict):
        return None
    card = item.get("note_card")
    if not card and item.get("model_type") == "note":
        card = item
    if not card:
        return None
    if not isinstance(card, dict):
        return None

    note_id = (
        card.get("note_id")
        or card.get("id")
        or item.get("id")
        or (card.get("note_id_str"))
    )
    if not note_id:
        return None
    note_id = str(note_id)

    title = (
        card.get("display_title")
        or card.get("title")
        or ""
    )
    raw_desc = (
        card.get("desc")
        or card.get("display_desc")
        or card.get("content")
        or card.get("text")
        or ""
    )
    desc = raw_desc.strip() if isinstance(raw_desc, str) else ""

    user = card.get("user") or {}
    if not isinstance(user, dict):
        user = {}
    nickname = user.get("nickname") or user.get("nick_name") or ""

    interact = card.get("interact_info") or {}
    if not isinstance(interact, dict):
        interact = {}
    likes = parse_interact_count(
        interact.get("liked_count")
        or interact.get("likedCount")
        or interact.get("like_count")
    )
    collects = parse_interact_count(
        interact.get("collected_count")
        or interact.get("collectedCount")
    )
    comments_count = parse_interact_count(
        interact.get("comment_count")
        or interact.get("commentCount")
    )

    ts = card.get("time") or card.get("create_time") or card.get("timestamp")
    publish_time = ""
    if ts is not None:
        try:
            if isinstance(ts, (int, float)) and ts > 1e12:
                publish_time = datetime.utcfromtimestamp(ts / 1000).strftime("%Y-%m-%d %H:%M:%S")
            elif isinstance(ts, (int, float)) and ts > 1e9:
                publish_time = datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
            else:
                publish_time = str(ts)
        except Exception:
            publish_time = str(ts)

    url = build_explore_url(note_id, item) if note_id else ""

    return {
        "note_id": note_id,
        "url": url,
        "title": (title or "").strip(),
        "desc": (desc or "").strip(),
        "publish_time": publish_time,
        "likes": likes if likes is not None else "",
        "collects": collects if collects is not None else "",
        "comments_count": comments_count if comments_count is not None else "",
        "author_masked": mask_author(nickname),
    }


def parse_search_response_body(body: Any) -> list[dict[str, Any]]:
    if not body or not isinstance(body, dict):
        return []
    data = api_search_payload(body)
    items = data.get("items") or data.get("notes") or []
    out: list[dict[str, Any]] = []
    for it in items:
        if isinstance(it, dict):
            n = extract_note_from_item(it)
            if n:
                out.append(n)
    return out


FIELDNAMES = [
    "track",
    "note_id",
    "url",
    "title",
    "desc",
    "publish_time",
    "likes",
    "collects",
    "comments_count",
    "author_masked",
    "search_keyword",
    "crawled_at",
    "body_full",
    "enrich_status",
    "enrich_error",
    "enriched_at",
]


class XhsSearchCrawler:
    def __init__(self, track: str, address: str | None = None):
        self.track = track
        self.cfg = load_config(track)
        self.address = address or os.environ.get("CHROMIUM_ADDRESS", "127.0.0.1:9527")
        self.seen_path = RAW_DIR / f".seen_{track}.json"
        self.out_path = RAW_DIR / f"xhs_{track}_raw.csv"
        self.seen: set[str] = set()
        self._load_seen()
        self.page: ChromiumPage | None = None

    def _load_seen(self) -> None:
        if self.seen_path.exists():
            try:
                data = json.loads(self.seen_path.read_text(encoding="utf-8"))
                self.seen = set(data.get("note_ids", []))
            except Exception:
                self.seen = set()

    def _save_seen(self) -> None:
        self.seen_path.parent.mkdir(parents=True, exist_ok=True)
        self.seen_path.write_text(
            json.dumps({"note_ids": sorted(self.seen)}, ensure_ascii=False, indent=0),
            encoding="utf-8",
        )

    def _ensure_csv_header(self) -> None:
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        if not self.out_path.exists():
            with open(self.out_path, "w", encoding="utf-8-sig", newline="") as f:
                w = csv.DictWriter(f, fieldnames=FIELDNAMES)
                w.writeheader()

    def _append_rows(self, rows: list[dict[str, Any]], keyword: str) -> int:
        self._ensure_csv_header()
        added = 0
        crawled_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        with open(self.out_path, "a", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=FIELDNAMES)
            for r in rows:
                nid = r["note_id"]
                if nid in self.seen:
                    continue
                self.seen.add(nid)
                w.writerow(
                    {
                        "track": self.track,
                        "note_id": nid,
                        "url": r.get("url", ""),
                        "title": r.get("title", ""),
                        "desc": r.get("desc", ""),
                        "publish_time": r.get("publish_time", ""),
                        "likes": r.get("likes", ""),
                        "collects": r.get("collects", ""),
                        "comments_count": r.get("comments_count", ""),
                        "author_masked": r.get("author_masked", ""),
                        "search_keyword": keyword,
                        "crawled_at": crawled_at,
                        "body_full": "",
                        "enrich_status": "pending",
                        "enrich_error": "",
                        "enriched_at": "",
                    }
                )
                added += 1
        return added

    def _scroll_feed(self, rounds: int = 3) -> None:
        if not self.page:
            return
        for _ in range(rounds):
            self.page.run_js("window.scrollBy(0, Math.floor(window.innerHeight * 0.9));")
            time.sleep(random.uniform(1.2, 2.5))

    def run(self) -> None:
        max_notes = int(self.cfg.get("max_notes", 5000))
        keywords = self.cfg.get("search_keywords") or []
        if not keywords:
            raise ValueError("search_keywords empty in config")

        self.page = ChromiumPage(self.address)
        self.page.listen.start(SEARCH_NOTES_SUBSTR)

        total_written = 0
        try:
            for kw in keywords:
                if total_written >= max_notes:
                    break
                q = quote(kw, safe="")
                url = f"{XHS_SEARCH_BASE}?keyword={q}&source=web_search_result_notes"
                self.page.get(url)
                time.sleep(random.uniform(2.0, 4.0))

                # First response after navigation
                batch_rounds = 0
                max_rounds = 80
                stagnant = 0
                while total_written < max_notes and batch_rounds < max_rounds:
                    # DrissionPage may return one DataPacket or a list when count>1
                    raw = self.page.listen.wait(count=5, timeout=10)
                    new_batch: list[dict[str, Any]] = []
                    packets: list[Any] = []
                    if raw:
                        packets = raw if isinstance(raw, list) else [raw]
                    for packet in packets:
                        try:
                            body = packet.response.body
                            if isinstance(body, str):
                                body = json.loads(body)
                            notes = parse_search_response_body(body)
                            new_batch.extend(notes)
                        except Exception:
                            continue
                    if new_batch:
                        stagnant = 0
                        n = self._append_rows(new_batch, kw)
                        total_written += n
                        print(f"[{self.track}] keyword={kw!r} +{n} (total {total_written})")
                    else:
                        stagnant += 1

                    self._scroll_feed(rounds=2)
                    batch_rounds += 1
                    if stagnant >= 6:
                        print(f"[{self.track}] no new packets for keyword {kw!r}, next keyword.")
                        break
                    time.sleep(random.uniform(0.8, 1.6))

                self._save_seen()
                time.sleep(random.uniform(2.0, 4.0))

        finally:
            self._save_seen()
            if self.page:
                self.page.listen.stop()
                self.page.quit()
            print(f"Done. Wrote up to {total_written} new notes -> {self.out_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Crawl Xiaohongshu search results by track config.")
    parser.add_argument(
        "--track",
        required=True,
        help="Track id matching config/{track}_keywords.yaml (e.g. dse, ielts_ai)",
    )
    parser.add_argument("--address", default=None, help="Chromium debugger address, e.g. 127.0.0.1:9222")
    args = parser.parse_args()
    if args.address:
        os.environ["CHROMIUM_ADDRESS"] = args.address
    track = validate_track(args.track)
    crawler = XhsSearchCrawler(track)
    crawler.run()


if __name__ == "__main__":
    main()
