# Data schema (XHS pipeline)

## Raw CSV (`data/raw/xhs_{track}_raw.csv`)

| Column | Description |
|--------|-------------|
| `track` | `dse` or `ielts_ai` |
| `note_id` | Platform note id (dedupe key) |
| `url` | Note detail URL from search API: `https://www.xiaohongshu.com/explore/{note_id}?xsec_token=...&xsec_source=pc_search&source=web_search_result_notes` when `xsec_token` is present in the item; otherwise plain `explore/{note_id}` (may 404 in browser) |
| `title` | Note title |
| `desc` | Snippet from **search** feed (may be short or empty) |
| `publish_time` | ISO date or raw string from page/API |
| `likes` | Integer (parsed) |
| `collects` | Integer or empty |
| `comments_count` | Integer or empty |
| `author_masked` | Hashed nickname |
| `search_keyword` | Which search query produced this row |
| `crawled_at` | When the search row was written |
| `body_full` | Full note text from **detail** `feed` API after `xhs_enrich`; empty until enriched |
| `enrich_status` | `pending` / `ok` / `fail` |
| `enrich_error` | Short error message if `fail` |
| `enriched_at` | When enrichment finished |

No phone numbers or private messages are stored.

## Comments CSV (`data/raw/xhs_{track}_comments.csv`)

One row per comment or reply (after enrichment).

| Column | Description |
|--------|-------------|
| `track` | `dse` or `ielts_ai` |
| `note_id` | Parent note |
| `comment_id` | Comment id |
| `parent_comment_id` | Empty for top-level; parent id for replies |
| `depth` | `0` = top-level, `1` = reply |
| `content` | Text |
| `like_count` | Parsed int or empty |
| `author_masked` | Hashed nickname |
| `create_time` | Raw from API |
| `crawled_at` | When this row was written |

Enrichment policy: at most **50 top-level** comments per note; all **replies** under those tops are kept.

## Processed CSV (`data/processed/xhs_{track}_processed.csv`)

Raw columns plus:

| Column | Description |
|--------|-------------|
| `valid` | `1` / `0` — passed length, keyword, exclude rules |
| `text_full` | `title` + `coalesce(body_full, desc)` + concatenated comment texts for that `note_id` |
| `sentiment_coarse` | `anxiety` / `neutral` / `positive` |

## Aggregates (`data/processed/metrics.json`)

Per-track: `raw_count`, `valid_count`, `sentiment_distribution`, `tfidf_top` (merged **post + comments** text), `monthly_counts`, `sample_quotes`, `comment_rows_total`, `avg_comments_per_valid_note`, `notes_with_comments`.
