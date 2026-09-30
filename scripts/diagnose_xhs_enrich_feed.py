"""
诊断：为何 xhs_enrich 能抓到评论但抓不到笔记正文。

请在项目根目录、已激活 conda 且能 import DrissionPage 的环境下运行，例如：

  cd /path/to/jd_drissionpage_new
  python scripts/diagnose_xhs_enrich_feed.py

或指定笔记与浏览器：

  python scripts/diagnose_xhs_enrich_feed.py --url "https://www.xiaohongshu.com/explore/<note_id>?..."
  set CHROMIUM_ADDRESS=127.0.0.1:9527

运行后把**完整终端输出**复制给维护者（可打码 cookie/token）。

依赖：与 crawler 相同（DrissionPage、pandas 等）。
"""
from __future__ import annotations

import argparse
import os
import random
import re
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from DrissionPage import ChromiumPage

from crawler.xhs_enrich import (
    LISTEN_SUBSTR,
    _bytes_to_json_text,
    _coerce_to_bytes,
    _decompress_body_bytes,
    _extract_note_body_from_dom,
    _fetch_feed_json_in_page,
    _is_comment_payload,
    _is_feed_payload,
    _network_disable_cache,
    _packets,
    _response_body,
)
from crawler.xhs_crawler import api_data_dict
from crawler.xhs_parse import parse_feed_body


def _hex_preview(data: bytes, n: int = 32) -> str:
    chunk = data[:n]
    return chunk.hex(" ")


def _safe_repr_body_preview(body: Any, limit: int = 120) -> str:
    if body is None:
        return "None"
    if isinstance(body, dict):
        return f"<dict keys={list(body)[:12]}...>"
    if isinstance(body, str):
        s = body.replace("\n", "\\n")
        return repr(s[:limit]) + ("..." if len(s) > limit else "")
    if isinstance(body, (bytes, bytearray, memoryview)):
        bb = bytes(body) if not isinstance(body, bytes) else body
        return f"<bytes len={len(bb)} head_hex={_hex_preview(bb, 16)}>"
    return repr(type(body).__name__)


def _drission_raw_flags(packet: Any) -> dict[str, Any]:
    out: dict[str, Any] = {}
    try:
        resp = packet.response
        out["response._raw_body_type"] = type(getattr(resp, "_raw_body", None)).__name__
        rb = getattr(resp, "_raw_body", None)
        if isinstance(rb, str) and rb:
            out["response._raw_body_len"] = len(rb)
            out["response._raw_body_preview"] = repr(rb[:80]) + ("..." if len(rb) > 80 else "")
        out["response._is_base64_body"] = getattr(resp, "_is_base64_body", None)
        h = getattr(resp, "headers", None)
        if h is not None:
            try:
                ce = h.get("Content-Encoding") or h.get("content-encoding")
                out["Content-Encoding"] = ce
            except Exception:
                pass
    except Exception as e:
        out["_drission_meta_error"] = str(e)
    return out


def _analyze_packet(packet: Any, note_id: str, index: int) -> None:
    print("\n" + "=" * 72)
    print(f"[packet #{index}]")
    try:
        url = packet.url
    except Exception as e:
        print(f"  url: <error {e}>")
        return
    print(f"  url: {url}")

    for k, v in _drission_raw_flags(packet).items():
        print(f"  {k}: {v}")

    try:
        raw_body = packet.response.body
    except Exception as e:
        print(f"  packet.response.body: <error {e}>")
        return

    print(f"  response.body type: {type(raw_body).__name__}")
    print(f"  response.body preview: {_safe_repr_body_preview(raw_body)}")

    bb = _coerce_to_bytes(raw_body)
    if bb is not None:
        print(f"  bytes len={len(bb)}  head_hex={_hex_preview(bb, 24)}")
        is_gzip = len(bb) >= 2 and bb[0] == 0x1F and bb[1] == 0x8B
        print(f"  looks_like_gzip: {is_gzip}")
        try:
            decompressed = _decompress_body_bytes(bb)
            print(f"  after _decompress_body_bytes: len={len(decompressed)} same_as_input={decompressed == bb}")
            txt = _bytes_to_json_text(bb)
            if txt:
                print(f"  _bytes_to_json_text len={len(txt)} starts_with={txt.lstrip()[:40]!r}")
        except Exception as e:
            print(f"  decompress/text pipeline error: {e}")

    parsed = _response_body(packet)
    if parsed is None:
        print("  _response_body: None (解析失败)")
    else:
        print(f"  _response_body: dict ok, top_keys={list(parsed.keys())[:15]}")
        feed_ok = _is_feed_payload(parsed)
        comment_ok = _is_comment_payload(parsed)
        print(f"  _is_feed_payload: {feed_ok}  _is_comment_payload: {comment_ok}")
        if feed_ok:
            bf = parse_feed_body(parsed, note_id)
            print(f"  parse_feed_body(note_id={note_id}) len={len(bf)} preview={bf[:80]!r}..." if len(bf) > 80 else f"  parse_feed_body len={len(bf)} text={bf!r}")
        if comment_ok:
            print("  (comment payload; 省略 parse_comment_page 行级详情)")


def _default_url_from_csv(track: str) -> tuple[str, str]:
    import pandas as pd

    p = ROOT / "data" / "raw" / f"xhs_{track}_raw.csv"
    if not p.exists():
        raise FileNotFoundError(p)
    df = pd.read_csv(p, encoding="utf-8-sig", dtype=str, keep_default_na=False)
    if df.empty:
        raise ValueError("CSV 无行")
    row = df.iloc[0]
    note_id = str(row.get("note_id") or "").strip()
    url = str(row.get("url") or "").strip()
    if not url and note_id:
        url = f"https://www.xiaohongshu.com/explore/{note_id}"
    if not note_id:
        m = re.search(r"/explore/([a-f0-9]+)", url, re.I)
        note_id = m.group(1) if m else ""
    return url, note_id


def main() -> None:
    parser = argparse.ArgumentParser(description="诊断 xhs_enrich 正文为空的原因")
    parser.add_argument("--track", default="dse", choices=("dse", "ielts_ai"))
    parser.add_argument("--url", default=None, help="笔记详情 URL（默认取 raw CSV 第一行）")
    parser.add_argument("--address", default=None, help="覆盖 CHROMIUM_ADDRESS")
    parser.add_argument("--rounds", type=int, default=20, help="监听轮数（每轮 wait+可选滚动）")
    parser.add_argument("--wait-count", type=int, default=12)
    parser.add_argument("--wait-timeout", type=float, default=9.0)
    parser.add_argument("--scroll", action="store_true", help="每轮末尾滚动（贴近 enrich 行为）")
    parser.add_argument(
        "--max-packets",
        type=int,
        default=45,
        help="最多详细打印多少个已拦截请求（避免刷屏）",
    )
    args = parser.parse_args()

    addr = args.address or os.environ.get("CHROMIUM_ADDRESS", "127.0.0.1:9527")
    os.environ["CHROMIUM_ADDRESS"] = addr

    print("=== 环境 ===")
    print(f"  python: {sys.version.split()[0]}")
    print(f"  cwd: {os.getcwd()}")
    print(f"  ROOT: {ROOT}")
    try:
        import DrissionPage as dp

        print(f"  DrissionPage: {getattr(dp, '__version__', 'unknown')}")
    except Exception as e:
        print(f"  DrissionPage: <import error {e}>")
    try:
        import brotli  # noqa: F401

        print("  brotli: installed")
    except ImportError:
        print("  brotli: not installed (可选，用于 Content-Encoding: br)")

    if args.url:
        note_url = args.url.strip()
        m = re.search(r"/explore/([a-f0-9]+)", note_url, re.I)
        note_id = m.group(1) if m else ""
    else:
        note_url, note_id = _default_url_from_csv(args.track)

    print(f"  CHROMIUM_ADDRESS: {addr}")
    print(f"  LISTEN_SUBSTR: {LISTEN_SUBSTR!r}")
    print(f"  note_id: {note_id}")
    print(f"  note_url: {note_url}")
    print()

    page = ChromiumPage(addr)
    pkt_index = 0
    printed = 0
    try:
        try:
            if getattr(page, "listen", None):
                page.listen.stop()
        except Exception:
            pass

        _network_disable_cache(page)
        page.listen.start(LISTEN_SUBSTR)
        print("=== 打开笔记页面 ===")
        page.get(note_url)
        time.sleep(random.uniform(1.5, 2.8))

        for round_i in range(args.rounds):
            raw = page.listen.wait(count=args.wait_count, timeout=args.wait_timeout)
            if raw is False:
                print(f"\n[round {round_i}] listen.wait 超时或未凑满 count（仍继续下一轮）")
            for packet in _packets(raw):
                if printed >= args.max_packets:
                    break
                pkt_index += 1
                printed += 1
                _analyze_packet(packet, note_id, pkt_index)

            if args.scroll:
                page.run_js(
                    "window.scrollBy(0, Math.floor(window.innerHeight * (0.35 + Math.random()*0.35)));"
                )
                time.sleep(0.9)
            if printed >= args.max_packets:
                break

        print("\n=== DOM 正文（enrich 与监听/feed 并列的主来源；优先于裸 POST /v1/feed）===")
        dom_len = len(_extract_note_body_from_dom(page))
        print(f"  _extract_note_body_from_dom 文本长度: {dom_len}")

        print("\n=== 页面内 POST /v1/feed（常因签名校验失败 code=-1，仅作补充）===")
        fj = _fetch_feed_json_in_page(page, note_id, note_url)
        if fj is None:
            print("  _fetch_feed_json_in_page: None（evaluate 失败或返回非 dict）")
        else:
            print(
                f"  code={fj.get('code')} success={fj.get('success')} msg={fj.get('msg')!r}"
            )
            ad = api_data_dict(fj)
            print(f"  feed JSON top_keys: {list(fj.keys())[:15]}")
            print(f"  api_data_dict keys: {list(ad.keys())[:20] if isinstance(ad, dict) else ad}")
            plen = len(parse_feed_body(fj, note_id))
            print(f"  parse_feed_body(note_id) 文本长度: {plen}")

        print("\n=== 结束 ===")
        print(f"已详细打印 {printed} 个拦截包（listen 目标为 {LISTEN_SUBSTR!r}）。")
    finally:
        try:
            if getattr(page, "listen", None):
                page.listen.stop()
        except Exception:
            pass
        try:
            page.quit()
        except Exception:
            pass


if __name__ == "__main__":
    main()
