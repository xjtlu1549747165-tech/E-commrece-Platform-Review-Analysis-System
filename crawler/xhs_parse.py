"""Parse Xiaohongshu JSON bodies for feed (note body) and comment/page."""

from __future__ import annotations

from typing import Any

from .xhs_crawler import api_data_dict, extract_note_from_item, mask_author, parse_interact_count


def _body_text_from_parsed(n: dict[str, Any]) -> str:
    desc = (n.get("desc") or "").strip()
    if desc:
        return desc
    return (n.get("title") or "").strip()


def _parse_feed_items_list(items_raw: Any, target: str) -> str:
    if not isinstance(items_raw, list) or not items_raw:
        return ""
    parsed: list[dict[str, Any]] = []
    for it in items_raw:
        if not isinstance(it, dict):
            continue
        n = extract_note_from_item(it)
        if n:
            parsed.append(n)
    if not parsed:
        return ""
    if target:
        for n in parsed:
            if str(n.get("note_id") or "") == target:
                # Matched id: use this card only (do not fall through to other notes' text).
                return _body_text_from_parsed(n)
    for n in parsed:
        t = _body_text_from_parsed(n)
        if t:
            return t
    return _body_text_from_parsed(parsed[0])


def _try_parse_embedded_note(data: dict[str, Any], target: str) -> str:
    """Some endpoints put the note under data.note / data.note_card without items[]."""
    candidates: list[dict[str, Any]] = []
    note = data.get("note")
    if isinstance(note, dict) and note:
        if isinstance(note.get("note_card"), dict):
            candidates.append(
                {"model_type": "note", "id": note.get("id"), "note_card": note["note_card"]}
            )
        else:
            candidates.append({"model_type": "note", "note_card": note})
    for key in ("note_card", "note_info"):
        node = data.get(key)
        if isinstance(node, dict) and node:
            candidates.append(
                {
                    "model_type": "note",
                    "note_card": node,
                    "id": node.get("note_id") or node.get("id"),
                }
            )
    for fake in candidates:
        n = extract_note_from_item(fake)
        if not n:
            continue
        if target and str(n.get("note_id") or "") != target:
            continue
        t = _body_text_from_parsed(n)
        if t:
            return t
    for fake in candidates:
        n = extract_note_from_item(fake)
        if not n:
            continue
        t = _body_text_from_parsed(n)
        if t:
            return t
    return ""


def parse_feed_body(body: Any, target_note_id: str | None = None) -> str:
    """
    Full note text from /api/sns/web/v1/feed (and similar) responses.

    Detail-page feed often returns multiple `items` — pass target_note_id from the URL
    to pick the matching card. Also handles single-note shapes (data.note / note_card).
    """
    if not body or not isinstance(body, dict):
        return ""
    data = api_data_dict(body)
    if not isinstance(data, dict):
        return ""
    target = (target_note_id or "").strip()

    from_items = _parse_feed_items_list(data.get("items"), target)
    if from_items:
        return from_items
    return _try_parse_embedded_note(data, target)


def _comment_row(
    track: str,
    note_id: str,
    cid: str,
    parent_comment_id: str,
    depth: int,
    content: str,
    like_count: Any,
    nickname: str | None,
    create_time: Any,
    crawled_at: str,
) -> dict[str, Any]:
    return {
        "track": track,
        "note_id": note_id,
        "comment_id": cid,
        "parent_comment_id": parent_comment_id,
        "depth": depth,
        "content": (content or "").replace("\n", " ").strip(),
        "like_count": parse_interact_count(like_count) if like_count is not None else "",
        "author_masked": mask_author(nickname),
        "create_time": str(create_time) if create_time is not None else "",
        "crawled_at": crawled_at,
    }


def parse_comment_page(
    body: Any,
    track: str,
    note_id: str,
    crawled_at: str,
    top_level_ids: set[str],
    max_top_level: int,
) -> tuple[list[dict[str, Any]], str | None]:
    """
    Parse one comment/page response. Mutates top_level_ids with new top-level ids (max max_top_level total).
    Returns (rows, cursor).
    """
    rows: list[dict[str, Any]] = []
    if not body or not isinstance(body, dict):
        return rows, None
    if body.get("code") not in (0, None) and body.get("success") is False:
        return rows, None
    data = api_data_dict(body)
    comments_raw = data.get("comments")
    if isinstance(comments_raw, list):
        comments = comments_raw
    else:
        comments = []
    cur = data.get("cursor")
    cursor = str(cur) if cur is not None and cur != "" else None

    for c in comments:
        if len(top_level_ids) >= max_top_level:
            break
        if not isinstance(c, dict):
            continue
        cid = str(c.get("id") or "")
        if not cid:
            continue
        if cid in top_level_ids:
            continue

        top_level_ids.add(cid)
        ui = c.get("user_info") or {}
        if not isinstance(ui, dict):
            ui = {}
        nick = ui.get("nickname") or ui.get("nick_name")
        rows.append(
            _comment_row(
                track,
                note_id,
                cid,
                "",
                0,
                str(c.get("content") or ""),
                c.get("like_count"),
                nick,
                c.get("create_time"),
                crawled_at,
            )
        )

        subs = c.get("sub_comments") or []
        if not isinstance(subs, list):
            subs = []
        for sub in subs:
            if not isinstance(sub, dict):
                continue
            sid = str(sub.get("id") or "")
            if not sid:
                continue
            sui = sub.get("user_info") or {}
            if not isinstance(sui, dict):
                sui = {}
            snick = sui.get("nickname") or sui.get("nick_name")
            rows.append(
                _comment_row(
                    track,
                    note_id,
                    sid,
                    cid,
                    1,
                    str(sub.get("content") or ""),
                    sub.get("like_count"),
                    snick,
                    sub.get("create_time"),
                    crawled_at,
                )
            )

    return rows, cursor
