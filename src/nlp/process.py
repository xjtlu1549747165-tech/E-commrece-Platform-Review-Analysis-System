"""
Clean raw XHS CSVs, apply validity rules, TF-IDF, coarse sentiment, export metrics.json.

Usage:
  python -m src.nlp.process
  python -m src.nlp.process --track dse
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import jieba
import pandas as pd
import yaml
from sklearn.feature_extraction.text import TfidfVectorizer

from src.nlp.sentiment_lexicon import coarse_sentiment

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
RAW = DATA / "raw"
PROC = DATA / "processed"
CONFIG = ROOT / "config"
STOPWORDS_PATH = DATA / "stopwords_zh.txt"
USER_DICT = DATA / "dict_user.txt"

RAW_MAIN_FIELDS = [
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


def _ensure_raw_main_columns(df: pd.DataFrame) -> pd.DataFrame:
    for c in RAW_MAIN_FIELDS:
        if c not in df.columns:
            df[c] = ""
    return df


def _body_or_desc(row: pd.Series) -> str:
    bf = str(row.get("body_full") or "").strip()
    if bf:
        return bf
    return str(row.get("desc") or "").strip()


def load_comments_blob_map(track: str) -> dict[str, str]:
    """note_id -> space-joined comment contents."""
    p = RAW / f"xhs_{track}_comments.csv"
    if not p.exists():
        return {}
    cdf = pd.read_csv(p, encoding="utf-8-sig", dtype=str)
    if cdf.empty or "note_id" not in cdf.columns or "content" not in cdf.columns:
        return {}
    parts: dict[str, list[str]] = {}
    for _, r in cdf.iterrows():
        nid = str(r.get("note_id") or "").strip()
        ct = str(r.get("content") or "").strip()
        if not nid or not ct:
            continue
        parts.setdefault(nid, []).append(ct)
    return {k: " ".join(v) for k, v in parts.items()}


def load_stopwords() -> set[str]:
    if not STOPWORDS_PATH.exists():
        return set()
    lines = STOPWORDS_PATH.read_text(encoding="utf-8").splitlines()
    return {x.strip() for x in lines if x.strip()}


def load_track_config(track: str) -> dict[str, Any]:
    name = "dse_keywords" if track == "dse" else "ielts_ai_keywords"
    with open(CONFIG / f"{name}.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def tokenize_zh(text: str, stop: set[str]) -> list[str]:
    words = jieba.lcut(text)
    out = []
    for w in words:
        w = w.strip()
        if len(w) < 2:
            continue
        if w in stop:
            continue
        if re.match(r"^[0-9\s\W]+$", w):
            continue
        out.append(w)
    return out


def _keyword_matches_blob(blob: str, keywords: list[str]) -> bool:
    """At least one configured keyword matches (phrase = all tokens present)."""
    for k in keywords:
        k = (k or "").strip()
        if not k:
            continue
        if " " in k or "\u3000" in k:
            parts = re.split(r"\s+", k.replace("\u3000", " "))
            if all((p in blob) or (p.isascii() and p.upper() in blob.upper()) for p in parts if p):
                return True
        else:
            if k in blob or (k.isascii() and k.upper() in blob.upper()):
                return True
    return False


def is_valid_row(
    row: pd.Series,
    cfg: dict[str, Any],
    must_hit: list[str],
) -> bool:
    min_len = int(cfg.get("min_text_length", 20))
    title = str(row.get("title", "") or "")
    main_text = _body_or_desc(row)
    blob = f"{title} {main_text}".strip()
    if len(blob) < min_len:
        return False
    ex = cfg.get("exclude_keywords") or []
    for bad in ex:
        if bad and bad in blob:
            return False
    for rx in cfg.get("exclude_regex") or []:
        if rx and re.search(rx, blob):
            return False
    if must_hit and not _keyword_matches_blob(blob, must_hit):
        return False
    # date filter
    da = cfg.get("date_after")
    if da and row.get("publish_time"):
        pt = str(row["publish_time"])[:10]
        try:
            if pt < str(da):
                return False
        except Exception:
            pass
    return True


def run_tfidf_top(corpus: list[str], stop: set[str], topn: int = 40) -> list[list[Any]]:
    if not corpus:
        return []

    def analyzer(text: str) -> list[str]:
        return tokenize_zh(text, stop)

    vectorizer = TfidfVectorizer(
        max_features=5000,
        analyzer=analyzer,
        token_pattern=None,
    )
    try:
        X = vectorizer.fit_transform(corpus)
    except ValueError:
        return []
    feats = vectorizer.get_feature_names_out()
    scores = X.sum(axis=0).A1
    pairs = sorted(zip(feats, scores), key=lambda x: -x[1])[:topn]
    return [[a, float(b)] for a, b in pairs]


def _find_font() -> str | None:
    for p in (
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\simhei.ttf",
        r"C:\Windows\Fonts\msyhbd.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    ):
        if Path(p).exists():
            return p
    return None


def _export_wordcloud_png(track: str, texts: list[str], root: Path) -> None:
    """Save word cloud to app/static/figures for Flask (best-effort)."""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from wordcloud import WordCloud
    except ImportError:
        return
    if not texts:
        return
    blob = "\n".join(texts[:2000])
    if len(blob) < 10:
        return
    stop = load_stopwords()
    freq: Counter[str] = Counter()
    for t in texts:
        for w in tokenize_zh(t, stop):
            freq[w] += 1
    if not freq:
        return
    font = _find_font()
    out_dir = root / "app" / "static" / "figures"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"wordcloud_{track}.png"
    try:
        wc = WordCloud(
            width=900,
            height=500,
            background_color="#1a2332",
            colormap="Blues",
            font_path=font,
            max_words=120,
        ).generate_from_frequencies(freq)
        plt.figure(figsize=(10, 5.5))
        plt.imshow(wc, interpolation="bilinear")
        plt.axis("off")
        plt.tight_layout()
        plt.savefig(out_path, dpi=120, bbox_inches="tight", facecolor="#1a2332")
        plt.close()
    except (ValueError, OSError) as e:
        import sys

        print(f"[wordcloud:{track}] skipped: {e}", file=sys.stderr)


def month_key_from_row(pub: str) -> str | None:
    if not pub or len(str(pub)) < 7:
        return None
    s = str(pub)[:7]
    if re.match(r"^\d{4}-\d{2}", s):
        return s
    return None


def process_track(track: str, stop: set[str]) -> dict[str, Any]:
    cfg = load_track_config(track)
    raw_path = RAW / f"xhs_{track}_raw.csv"
    if not raw_path.exists():
        return {
            "track": track,
            "error": f"missing {raw_path}",
            "raw_count": 0,
            "valid_count": 0,
        }

    df = pd.read_csv(raw_path, encoding="utf-8-sig")
    df = _ensure_raw_main_columns(df)
    raw_count = len(df)

    cmap = load_comments_blob_map(track)
    must_keywords = list(cfg.get("search_keywords") or [])

    def _build_text_full(row: pd.Series) -> str:
        nid = str(row.get("note_id") or "").strip()
        core = f"{str(row.get('title') or '')} {_body_or_desc(row)}".strip()
        extra = cmap.get(nid, "")
        if extra:
            return f"{core} {extra}".strip()
        return core

    df["text_full"] = df.apply(_build_text_full, axis=1)
    df["valid"] = df.apply(lambda r: is_valid_row(r, cfg, must_keywords), axis=1).astype(int)
    valid_df = df[df["valid"] == 1].copy()
    valid_count = len(valid_df)

    valid_df["sentiment_coarse"] = valid_df["text_full"].apply(coarse_sentiment)

    out_csv = PROC / f"xhs_{track}_processed.csv"
    PROC.mkdir(parents=True, exist_ok=True)
    valid_df.to_csv(out_csv, index=False, encoding="utf-8-sig")

    texts = valid_df["text_full"].tolist()
    tfidf_top = run_tfidf_top(texts, stop)

    _export_wordcloud_png(track, texts, ROOT)

    sent_dist = Counter(valid_df["sentiment_coarse"])
    monthly: Counter[str] = Counter()
    for _, r in valid_df.iterrows():
        mk = month_key_from_row(str(r.get("publish_time", "")))
        if mk:
            monthly[mk] += 1

    quotes: list[str] = []
    for t in valid_df["text_full"].head(20):
        s = str(t).replace("\n", " ").strip()
        if 15 <= len(s) <= 200:
            quotes.append(s[:180])
        if len(quotes) >= 5:
            break

    notes_with_comments = 0
    if cmap:
        vn = valid_df["note_id"].astype(str)
        notes_with_comments = int(vn.map(lambda x: 1 if x in cmap and cmap[x] else 0).sum())

    comment_rows_total = 0
    cp = RAW / f"xhs_{track}_comments.csv"
    if cp.exists():
        try:
            comment_rows_total = len(pd.read_csv(cp, encoding="utf-8-sig"))
        except Exception:
            comment_rows_total = 0

    avg_c = (
        (comment_rows_total / notes_with_comments) if notes_with_comments else 0.0
    )

    return {
        "track": track,
        "raw_count": raw_count,
        "valid_count": valid_count,
        "sentiment_distribution": dict(sent_dist),
        "tfidf_top": tfidf_top,
        "tfidf_note": "Merged post title, body (body_full or desc), and all scraped comments for this track.",
        "monthly_counts": dict(sorted(monthly.items())),
        "sample_quotes": quotes[:5],
        "processed_csv": str(out_csv.relative_to(ROOT)),
        "comment_rows_total": comment_rows_total,
        "avg_comments_per_valid_note": round(avg_c, 3) if notes_with_comments else 0.0,
        "notes_with_comments": notes_with_comments,
    }


def main() -> None:
    if USER_DICT.exists():
        jieba.load_userdict(str(USER_DICT))
    stop = load_stopwords()

    parser = argparse.ArgumentParser()
    parser.add_argument("--track", choices=("dse", "ielts_ai", "all"), default="all")
    args = parser.parse_args()

    tracks = ["dse", "ielts_ai"] if args.track == "all" else [args.track]
    metrics: dict[str, Any] = {}
    for t in tracks:
        metrics[t] = process_track(t, stop)

    PROC.mkdir(parents=True, exist_ok=True)
    out_json = PROC / "metrics.json"
    out_json.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {out_json}")


if __name__ == "__main__":
    main()
