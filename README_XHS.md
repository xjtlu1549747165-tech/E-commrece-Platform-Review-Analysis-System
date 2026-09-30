# Xiaohongshu — DSE vs IELTS AI prep (INF101TC pipeline)

## Prerequisites

- Python 3.10+ (this repo is tested with a Conda env named **`crawler`** — activate it before running any commands below).
- Google Chrome / Chromium with **remote debugging** enabled (DrissionPage connects via `CHROMIUM_ADDRESS`, default `127.0.0.1:9527`).
- Log in to [xiaohongshu.com](https://www.xiaohongshu.com) once in that browser if search or comments require an account.

## Install

```bash
conda activate crawler
cd jd_drissionpage_new
pip install -r requirements.txt
copy .env.example .env
```

Edit `.env`: set `CHROMIUM_ADDRESS` and (optional) `OPENAI_API_KEY` for the brief.

## 1. Search crawl (two runs: DSE + competitor track)

```bash
python -m crawler.xhs_crawler --track dse
python -m crawler.xhs_crawler --track ielts_ai
```

Outputs append to `data/raw/xhs_{track}_raw.csv` and dedupe via `data/raw/.seen_{track}.json`. Each row’s `url` includes `xsec_token` from the `search/notes` response when available (needed for Web 版打开详情页). New rows include `enrich_status=pending` and empty `body_full` until step 2.

**Re-crawl search** if you have older CSVs whose `url` has no query string—enrich needs the long URL to load the note. To rebuild the raw sheet with tokens, back up `data/raw/xhs_{track}_raw.csv`, delete it and `data/raw/.seen_{track}.json`, then run `python -m crawler.xhs_crawler --track {track}` again (or use a fresh filename and merge manually).

**Note:** Listener targets URLs containing `search/notes`.

## 2. Enrich: full post body + comments (slow)

Uses the logged-in browser session. Intercepts `sns/web/v1/feed` (full `desc` in `note_card`) and `sns/web/v2/comment/page` (up to **50 top-level** comments per note; **all replies** under those tops).

```bash
python -m crawler.xhs_enrich --track dse
python -m crawler.xhs_enrich --track ielts_ai
```

Optional: `--limit 100` to process only the next 100 pending rows; `--start-row N` to resume by DataFrame index.

Updates `xhs_{track}_raw.csv` (`body_full`, `enrich_status`, …) and writes `data/raw/xhs_{track}_comments.csv`.

Config: `enrich_delay_sec`, `max_top_level_comments` in [`config/dse_keywords.yaml`](config/dse_keywords.yaml) / `ielts_ai_keywords.yaml`.

## 3. NLP + metrics + word clouds (post + comments)

`text_full` = **title** + **body** (`body_full` if present, else search `desc`) + **all comment texts** for that note from the comments CSV. TF-IDF / sentiment / wordcloud use this merged text.

```bash
python -m src.nlp.process
```

Writes:

- `data/processed/xhs_dse_processed.csv`, `xhs_ielts_ai_processed.csv`
- `data/processed/metrics.json` (includes `comment_rows_total`, `notes_with_comments`, `avg_comments_per_valid_note`, `tfidf_note`)
- `app/static/figures/wordcloud_*.png` (if a Chinese font is found on the system)

## 4. Notebook (optional charts)

Open `notebooks/analysis_xhs.ipynb` (set kernel to project env). Figures save under `Visualization/`.

## 5. Flask dashboard

```bash
python run_dashboard.py
```

Browse to `http://127.0.0.1:5000`.

## 6. LLM strategic brief (optional)

```bash
python scripts/generate_brief.py --out docs/strategic_brief.md
```

## Data schema

See [docs/DATA_SCHEMA.md](docs/DATA_SCHEMA.md).

## Architecture diagram

[docs/architecture.drawio](docs/architecture.drawio) — open with [draw.io](https://app.diagrams.net/).

## Demo rows

Small demo CSVs may ship under `data/raw/` for smoke tests. Replace with real crawled data for your report.
