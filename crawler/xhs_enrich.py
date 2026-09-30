"""
Second-phase enrichment: open each note detail, intercept feed + comment/page APIs.

Requires logged-in Chromium (CHROMIUM_ADDRESS). Run after xhs_crawler search phase.

Usage:
  python -m crawler.xhs_enrich --track dse
  python -m crawler.xhs_enrich --track dse --limit 50
"""
from __future__ import annotations

import argparse
import base64
import gzip
import json
import os
import random
import time
import zlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import pandas as pd
import yaml
from DrissionPage import ChromiumPage

from crawler.xhs_crawler import FIELDNAMES, ROOT, api_data_dict, load_config, validate_track
from crawler.xhs_parse import parse_comment_page, parse_feed_body

RAW_DIR = ROOT / "data" / "raw"
CONFIG_DIR = ROOT / "config"

# Match both feed and comment APIs (filter by JSON shape in handlers).
LISTEN_SUBSTR = "xiaohongshu.com/api/sns/web"

COMMENT_FIELDS = [
    "track",
    "note_id",
    "comment_id",
    "parent_comment_id",
    "depth",
    "content",
    "like_count",
    "author_masked",
    "create_time",
    "crawled_at",
]


def _ensure_main_columns(df: pd.DataFrame) -> pd.DataFrame:
    for c in FIELDNAMES:
        if c not in df.columns:
            df[c] = ""
    if "enrich_status" in df.columns:
        df["enrich_status"] = df["enrich_status"].fillna("pending").replace("", "pending")
    else:
        df["enrich_status"] = "pending"
    return df


def _coerce_to_bytes(body: Any) -> bytes | None:
    if isinstance(body, bytes):
        return body
    if isinstance(body, bytearray):
        return bytes(body)
    if isinstance(body, memoryview):
        return body.tobytes()
    return None


def _decompress_body_bytes(raw: bytes) -> bytes:
    """
    CDP getResponseBody is often base64(gzip(JSON)). DrissionPage decodes base64 to bytes
    but does NOT unzip; Response.body then returns raw gzip bytes (json.loads fails in DP).
    """
    if not raw:
        return raw
    if len(raw) >= 2 and raw[0] == 0x1F and raw[1] == 0x8B:
        try:
            return gzip.decompress(raw)
        except OSError:
            return raw
    if len(raw) >= 2 and raw[0] == 0x78 and raw[1] in (0x01, 0x9C, 0xDA):
        try:
            return zlib.decompress(raw)
        except zlib.error:
            return raw
    # Plain JSON text bytes — do not run brotli on these.
    stripped = raw.lstrip()
    if stripped[:1] in (b"{", b"["):
        return raw
    try:
        import brotli

        return brotli.decompress(raw)
    except Exception:
        return raw


def _bytes_to_json_text(raw: bytes) -> str | None:
    data = _decompress_body_bytes(raw)
    try:
        t = data.decode("utf-8")
    except UnicodeDecodeError:
        t = data.decode("utf-8", errors="replace")
    s = t.strip()
    return s if s else None


def _response_body(packet: Any) -> dict[str, Any] | None:
    """
    DrissionPage DataPacket.response.body:
    - If CDP body was JSON text, DP already json.loads -> dict.
    - If base64-encoded binary (common for gzip), DP returns bytes -> must unzip then loads.
    See DrissionPage _units/listener.py Response.body.
    """
    try:
        b = packet.response.body
    except Exception:
        return None
    if b is None:
        return None
    if isinstance(b, dict):
        return b
    bb = _coerce_to_bytes(b)
    if bb is not None:
        text = _bytes_to_json_text(bb)
        if text:
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                pass
    if isinstance(b, str):
        s = b.strip()
        if not s:
            return None
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            try:
                pad = (-len(s)) % 4
                raw = base64.b64decode(s + "=" * pad, validate=False)
                text = _bytes_to_json_text(raw)
                return json.loads(text) if text else None
            except Exception:
                return None
    return None


def _is_feed_payload(body: dict[str, Any]) -> bool:
    d = api_data_dict(body)
    items = d.get("items")
    if isinstance(items, list) and len(items) > 0:
        return True
    for k in ("note", "note_card", "note_info"):
        node = d.get(k)
        if isinstance(node, dict) and node:
            return True
    return False


def _is_comment_payload(body: dict[str, Any]) -> bool:
    d = api_data_dict(body)
    return "comments" in d


def _packets(raw: Any) -> list[Any]:
    if not raw:
        return []
    return raw if isinstance(raw, list) else [raw]


def _network_disable_cache(page: ChromiumPage) -> None:
    """Avoid SPA serving note detail from cache without re-requesting /v1/feed."""
    try:
        page.run_cdp("Network.enable")
        page.run_cdp("Network.setCacheDisabled", cacheDisabled=True)
    except Exception:
        pass


def _cdp_evaluate_json(page: ChromiumPage, expression: str) -> Any | None:
    """Runtime.evaluate with awaitPromise + returnByValue; return Python value or None."""
    try:
        r = page.run_cdp(
            "Runtime.evaluate",
            expression=expression,
            awaitPromise=True,
            returnByValue=True,
            userGesture=True,
        )
    except Exception:
        return None
    if not r or not isinstance(r, dict):
        return None
    # CDP Runtime.evaluate: result.result.value 或 result.value
    top = r.get("result")
    if not isinstance(top, dict):
        return None
    if top.get("exceptionDetails"):
        return None
    if "value" in top:
        return top.get("value")
    mid = top.get("result")
    if isinstance(mid, dict) and "value" in mid:
        return mid.get("value")
    return None


def _xsec_source_try_order(note_url: str) -> list[str]:
    """URL 里的 xsec_token 通常与 query 里的 xsec_source 成对；该来源应最先尝试 POST。"""
    q = parse_qs(urlparse(note_url).query)
    u = (q.get("xsec_source") or [""])[0].strip()
    out: list[str] = []
    if u:
        out.append(u)
    for x in ("pc_feed", "pc_search"):
        if x not in out:
            out.append(x)
    return out


def _feed_api_response_has_note(d: dict[str, Any]) -> bool:
    """True if /v1/feed returned usable note data (ReaJason/xhs: res['items'][0]['note_card'])."""
    data = api_data_dict(d)
    if not data:
        return False
    items = data.get("items")
    if isinstance(items, list) and len(items) > 0:
        return True
    if data.get("note") or data.get("note_card"):
        return True
    return False


def _fetch_feed_json_in_page(page: ChromiumPage, note_id: str, note_url: str) -> dict[str, Any] | None:
    """
    POST /v1/feed（与站内请求尽量一致）。裸 fetch 仍可能被 X-s 等签名校验拒绝（code=-1），
    此时由 DOM 回退补正文。
    """
    q = parse_qs(urlparse(note_url).query)
    token = (q.get("xsec_token") or [""])[0].strip()
    ref = json.dumps(note_url, ensure_ascii=False)
    origin = json.dumps("https://www.xiaohongshu.com", ensure_ascii=False)
    last: dict[str, Any] | None = None
    for xsec_source in _xsec_source_try_order(note_url):
        payload: dict[str, Any] = {
            "source_note_id": note_id,
            "image_formats": ["jpg", "webp", "avif"],
            "extra": {"need_body_topic": 1},
            "xsec_source": xsec_source,
        }
        if token:
            payload["xsec_token"] = token
        pl = json.dumps(payload, ensure_ascii=False)
        expr = f"""(async () => {{
  const payload = {pl};
  const res = await fetch('https://edith.xiaohongshu.com/api/sns/web/v1/feed', {{
    method: 'POST',
    credentials: 'include',
    headers: {{
      'content-type': 'application/json',
      'referer': {ref},
      'origin': {origin},
      'accept': 'application/json, text/plain, */*',
      'accept-language': 'zh-CN,zh;q=0.9,en;q=0.8',
    }},
    body: JSON.stringify(payload),
  }});
  return await res.json();
}})()"""
        val = _cdp_evaluate_json(page, expr)
        last = val if isinstance(val, dict) else last
        if isinstance(val, dict) and _feed_api_response_has_note(val):
            return val
    return last


def _extract_note_body_from_dom(page: ChromiumPage) -> str:
    """
    Web 版笔记正文在已渲染 DOM 中；当 /v1/feed 无数据或被签名校验拒绝（code=-1）时作为正文来源。
    选择器随前端改版可能需更新。
    """
    try:
        w = getattr(page, "wait", None)
        if w is not None and hasattr(w, "doc_loaded"):
            w.doc_loaded()
    except Exception:
        pass
    time.sleep(random.uniform(0.35, 0.75))

    js = """
    return (function(){
      var sels = [
        '#detail-desc',
        '#note-desc',
        '.note-content .note-text',
        '.note-text',
        '[class*="note-scroller"] .desc',
        '#noteContainer .desc'
      ];
      var i, el, t;
      for (i = 0; i < sels.length; i++) {
        el = document.querySelector(sels[i]);
        if (el) {
          t = (el.innerText || el.textContent || '').trim();
          if (t.length >= 10) return t;
        }
      }
      return '';
    })();
    """
    try:
        t = page.run_js(js)
        if isinstance(t, str) and t.strip():
            return t.strip()
    except Exception:
        pass
    return ""


def enrich_one_note(
    page: ChromiumPage,
    track: str,
    note_id: str,
    note_url: str,
    max_top: int,
    delay_scroll: float,
) -> tuple[str, list[dict[str, Any]], str | None]:
    """
    Returns (body_full, comment_rows, error_message).
    """
    crawled_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    body_full = ""
    top_level_ids: set[str] = set()
    merged: dict[str, dict[str, Any]] = {}
    # DrissionPage 的 listen 可能是惰性初始化的；不要在 start 前无条件调用 stop。
    # 另外，对 stop 做兜底，避免 listen 为 None 时直接崩溃。
    try:
        if getattr(page, "listen", None):
            page.listen.stop()
    except Exception:
        pass

    _network_disable_cache(page)
    page.listen.start(LISTEN_SUBSTR)
    page.get(note_url)
    time.sleep(random.uniform(1.5, 2.8))

    max_rounds = 22
    stagnant = 0
    prev_merged = 0
    prev_body_len = 0
    for _ in range(max_rounds):
        raw = page.listen.wait(count=12, timeout=9)
        got = False
        for packet in _packets(raw):
            body = _response_body(packet)
            if not body or not isinstance(body, dict):
                continue
            if _is_feed_payload(body):
                bf = parse_feed_body(body, note_id)
                if bf:
                    body_full = bf
                    got = True
            if _is_comment_payload(body):
                rows, _cursor = parse_comment_page(
                    body, track, note_id, crawled_at, top_level_ids, max_top
                )
                for r in rows:
                    merged[r["comment_id"]] = r
                if rows:
                    got = True

        if len(merged) > prev_merged or len(body_full) > prev_body_len:
            stagnant = 0
            prev_merged = len(merged)
            prev_body_len = len(body_full)
        elif got:
            stagnant = 0
        else:
            stagnant += 1

        if len(top_level_ids) >= max_top:
            break
        if body_full and len(merged) > 0 and stagnant >= 5:
            break

        page.run_js(
            "window.scrollBy(0, Math.floor(window.innerHeight * (0.35 + Math.random()*0.35)));"
        )
        time.sleep(delay_scroll)
        if stagnant >= 12 and body_full:
            break

    try:
        if getattr(page, "listen", None):
            page.listen.stop()
    except Exception:
        pass

    # 监听不到 feed、且裸 POST /v1/feed 常被签名校验拒绝（code=-1）时，以 DOM 为主来源（见 diagnose 脚本验证）。
    if not body_full:
        dom_txt = _extract_note_body_from_dom(page)
        if dom_txt:
            body_full = dom_txt
    if not body_full:
        fed = _fetch_feed_json_in_page(page, note_id, note_url)
        if fed:
            bf = parse_feed_body(fed, note_id)
            if bf:
                body_full = bf

    err: str | None = None
    if not body_full:
        err = "empty_feed_body"

    return body_full, list(merged.values()), err


def run_enrich(track: str, limit: int | None, start_row: int, address: str | None) -> None:
    cfg = load_config(track)
    delay_between = float(cfg.get("enrich_delay_sec", 3))
    max_top = int(cfg.get("max_top_level_comments", 50))
    addr = address or os.environ.get("CHROMIUM_ADDRESS", "127.0.0.1:9527")

    main_path = RAW_DIR / f"xhs_{track}_raw.csv"
    if not main_path.exists():
        raise FileNotFoundError(main_path)

    df = pd.read_csv(main_path, encoding="utf-8-sig", dtype=str, keep_default_na=False)
    df = _ensure_main_columns(df)
    comments_path = RAW_DIR / f"xhs_{track}_comments.csv"

    page = ChromiumPage(addr)
    done = 0
    last_i: int = start_row
    try:
        for i, row in df.iterrows():
            if i < start_row:
                continue
            if limit is not None and done >= limit:
                break
            status = str(row.get("enrich_status") or "pending").strip()
            if status == "ok":
                continue

            last_i = int(i)
            note_id = str(row.get("note_id") or "").strip()
            if not note_id:
                continue
            note_url = str(row.get("url") or "").strip()
            if not note_url:
                note_url = f"https://www.xiaohongshu.com/explore/{note_id}"

            try:
                body_full, crows, err = enrich_one_note(
                    page, track, note_id, note_url, max_top, 0.9
                )
                now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
                df.at[i, "body_full"] = body_full
                if not body_full:
                    df.at[i, "enrich_status"] = "fail"
                    df.at[i, "enrich_error"] = err or "empty_feed_body"
                    df.at[i, "enriched_at"] = now
                else:
                    df.at[i, "enrich_status"] = "ok"
                    df.at[i, "enrich_error"] = err or ""
                    df.at[i, "enriched_at"] = now

                if crows:
                    if comments_path.exists():
                        cdf = pd.read_csv(comments_path, encoding="utf-8-sig", dtype=str)
                        cdf = cdf[cdf["note_id"].astype(str) != note_id]
                    else:
                        cdf = pd.DataFrame(columns=COMMENT_FIELDS)
                    nd = pd.DataFrame(crows)
                    for c in COMMENT_FIELDS:
                        if c not in nd.columns:
                            nd[c] = ""
                    nd = nd[COMMENT_FIELDS]
                    cdf = pd.concat([cdf, nd], ignore_index=True)
                    cdf.to_csv(comments_path, index=False, encoding="utf-8-sig")

                df.to_csv(main_path, index=False, encoding="utf-8-sig")
                done += 1
                tag = "ok" if body_full else "partial"
                print(
                    f"[enrich] {note_id} {tag} body={len(body_full)} comments={len(crows)} ({done})"
                )
            except Exception as e:
                now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
                df.at[i, "enrich_status"] = "fail"
                df.at[i, "enrich_error"] = str(e)[:200]
                df.at[i, "enriched_at"] = now
                df.to_csv(main_path, index=False, encoding="utf-8-sig")
                print(f"[enrich] {note_id} fail: {e}")

            time.sleep(random.uniform(delay_between * 0.8, delay_between * 1.2))

    finally:
        try:
            page.quit()
        except Exception:
            pass

    prog = RAW_DIR / f".enrich_progress_{track}.json"
    prog.write_text(
        json.dumps({"last_row": last_i, "done_count": done}, indent=2),
        encoding="utf-8",
    )
    print(f"Enrichment finished. Updated {done} rows.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Enrich raw CSV with feed body + comments.")
    parser.add_argument(
        "--track",
        required=True,
        help="Track id matching config/{track}_keywords.yaml",
    )
    parser.add_argument("--limit", type=int, default=None, help="Max notes to process")
    parser.add_argument("--start-row", type=int, default=0, help="DataFrame row index to start")
    parser.add_argument("--address", default=None)
    args = parser.parse_args()
    if args.address:
        os.environ["CHROMIUM_ADDRESS"] = args.address
    track = validate_track(args.track)
    run_enrich(track, args.limit, args.start_row, args.address)


if __name__ == "__main__":
    main()
