"""Show message volume statistics from ChatGPT and/or Claude export files.

Usage:
  python3 usage_stats.py <file1.json> [file2.json ...] [--timezone TZ] [--start-date YYYY-MM-DD] [--end-date YYYY-MM-DD]

Each file is auto-detected as ChatGPT (has 'mapping') or Claude (has 'chat_messages').
Thinking blocks, tool_use, and tool_result are excluded from AI word/char counts.
"""

import argparse
from pathlib import Path
import json
import sys
from datetime import datetime, timezone as dt_timezone
from collections import defaultdict
from pytz import timezone
from pytz.exceptions import UnknownTimeZoneError
from tzlocal import get_localzone


# ---------- TIMEZONE ----------


def resolve_timezone(tz_name=None):
    """Return a timezone object. Warns and falls back to UTC on failure."""
    if tz_name:
        try:
            return timezone(tz_name)
        except UnknownTimeZoneError:
            print(f'Warning: Unknown timezone "{tz_name}", falling back to UTC.')
            return dt_timezone.utc
    try:
        return get_localzone()
    except Exception:
        print("Warning: Could not detect local timezone, falling back to UTC.")
        return dt_timezone.utc


# ---------- TIMESTAMP ----------


def _to_utc(timestamp) -> datetime:
    """Parse a Unix float or ISO 8601 string and return an aware UTC datetime.

    Raises ValueError/TypeError/OSError on parse failure (callers catch these).
    """
    if isinstance(timestamp, (int, float)):
        return datetime.fromtimestamp(timestamp, tz=dt_timezone.utc)
    ts = timestamp.replace("Z", "+00:00")
    utc = datetime.fromisoformat(ts)
    if utc.tzinfo is None:
        utc = utc.replace(tzinfo=dt_timezone.utc)
    return utc


def to_local_date(timestamp, tz) -> str | None:
    """Convert a Unix float or ISO 8601 string to a 'YYYY-MM-DD' date in local time."""
    if timestamp is None:
        return None
    try:
        return _to_utc(timestamp).astimezone(tz).strftime("%Y-%m-%d")
    except (ValueError, TypeError, OSError):
        return None


def to_local_iso(timestamp, tz) -> str | None:
    """Convert a Unix float or ISO 8601 string to a full ISO 8601 datetime in local time."""
    if timestamp is None:
        return None
    try:
        return _to_utc(timestamp).astimezone(tz).isoformat()
    except (ValueError, TypeError, OSError):
        return None


def to_local_str(timestamp, tz) -> str:
    """Convert a Unix float or ISO 8601 string to 'YYYY-MM-DD HH:MM:SS' in local time."""
    if timestamp is None:
        return "Unknown time"
    try:
        return _to_utc(timestamp).astimezone(tz).strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError, OSError):
        return f"Unknown time ({timestamp})"


# ---------- TEXT EXTRACTION ----------


def count(text: str) -> tuple[int, int]:
    """Return (words, characters) for a string."""
    return len(text.split()), len(text)


def add(a: tuple, b: tuple) -> tuple:
    return (a[0] + b[0], a[1] + b[1])


def extract_claude_text(content_blocks) -> str:
    """Concatenate only 'text' blocks from a Claude message."""
    parts = []
    for block in content_blocks:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(block.get("text", ""))
    return " ".join(parts)


def extract_chatgpt_text(parts) -> str:
    """Concatenate string parts from a ChatGPT message."""
    return " ".join(p for p in parts if isinstance(p, str))


# ---------- PARSERS ----------


def parse_claude(data: list, tz) -> list[dict]:
    """Return list of message records from a Claude export."""
    records = []
    for conv in data:
        conv_id = conv.get("uuid", "")
        conv_title = conv.get("name", "") or ""
        conv_created_at = to_local_iso(conv.get("created_at"), tz)
        conv_updated_at = to_local_iso(conv.get("updated_at"), tz)
        for msg in conv.get("chat_messages", []):
            sender = msg.get("sender", "")
            if sender not in ("human", "assistant"):
                continue
            date = to_local_date(msg.get("created_at"), tz)
            if not date:
                continue
            content = msg.get("content", [])
            if isinstance(content, list):
                text = extract_claude_text(content)
            else:
                text = msg.get("text", "")
            if not text.strip():
                continue
            w, c = count(text)
            records.append({
                "date": date, "role": sender, "words": w, "chars": c,
                "conv_id": conv_id, "source": "Claude",
                "conv_title": conv_title,
                "conv_created_at": conv_created_at,
                "conv_updated_at": conv_updated_at,
                "msg_ts": to_local_iso(msg.get("created_at"), tz),
                "model": "Claude",
                "custom_gpt": None,
                "memory_scope": None,
                "voice": False,
            })
    return records


def parse_chatgpt(data: list, tz) -> list[dict]:
    """Return list of message records from a ChatGPT export."""
    records = []
    for conv in data:
        conv_id = conv.get("id", "")
        conv_title = conv.get("title", "") or ""
        custom_gpt = (conv.get("gpt_metadata") or {}).get("display_name") or conv.get("gizmo_id") or None
        memory_scope = conv.get("memory_scope") or None
        for node in conv.get("mapping", {}).values():
            msg = node.get("message") if isinstance(node, dict) else None
            if not msg:
                continue
            role = msg.get("author", {}).get("role", "")
            if role not in ("user", "assistant"):
                continue
            date = to_local_date(msg.get("create_time"), tz)
            if not date:
                continue
            parts = msg.get("content", {}).get("parts", [])
            text = extract_chatgpt_text(parts)
            if not text.strip():
                continue
            w, c = count(text)
            norm_role = "human" if role == "user" else "assistant"
            _meta = msg.get("metadata", {})
            model_slug = _meta.get("model_slug") or "ChatGPT"
            voice = bool(_meta.get("voice_mode_message")) or ("real_time_audio_has_video" in _meta)
            records.append({
                "date": date, "role": norm_role, "words": w, "chars": c,
                "conv_id": conv_id, "source": "ChatGPT",
                "conv_title": conv_title,
                "conv_created_at": None,
                "conv_updated_at": None,
                "msg_ts": to_local_iso(msg.get("create_time"), tz),
                "model": model_slug,
                "custom_gpt": custom_gpt,
                "memory_scope": memory_scope,
                "voice": voice,
            })
    return records


def detect_and_parse(path: Path, tz) -> tuple[list[dict], str, int]:
    """Load a JSON file, detect its format, and return (records, source_label, n_conversations)."""
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError(f"{path.name}: expected a JSON array at top level")

    fmt = None
    for conv in data:
        if "chat_messages" in conv:
            fmt = "Claude"
            break
        if "mapping" in conv:
            fmt = "ChatGPT"
            break
    if fmt is None:
        raise ValueError(
            f"{path.name}: could not detect format (no 'chat_messages' or 'mapping' key found)"
        )

    records = parse_claude(data, tz) if fmt == "Claude" else parse_chatgpt(data, tz)
    return records, fmt, len(data)


# ---------- CONVERSATION STATS ----------


def conv_stats(records: list[dict]) -> list[dict]:
    """Return one dict per conversation with message and word counts."""
    convs: dict[str, dict] = {}
    for r in records:
        cid = r["conv_id"]
        if cid not in convs:
            convs[cid] = {
                "conv_id": cid,
                "source": r["source"],
                "title": r.get("conv_title", ""),
                "created_at": r["conv_created_at"],
                "updated_at": r["conv_updated_at"],
                "_msg_ts_list": [],
                "messages": 0,
                "user_words": 0,
                "ai_words": 0,
            }
        convs[cid]["messages"] += 1
        if r["msg_ts"]:
            convs[cid]["_msg_ts_list"].append(r["msg_ts"])
        if r["role"] == "human":
            convs[cid]["user_words"] += r["words"]
        else:
            convs[cid]["ai_words"] += r["words"]

    for c in convs.values():
        c["total_words"] = c["user_words"] + c["ai_words"]
        if c["source"] == "ChatGPT" and c["_msg_ts_list"]:
            c["created_at"] = min(c["_msg_ts_list"])
            c["updated_at"] = max(c["_msg_ts_list"])
        del c["_msg_ts_list"]

    return list(convs.values())


# ---------- AGGREGATION ----------

ZERO = (0, 0)  # (words, chars)


def aggregate(records: list[dict]) -> dict:
    """Build nested totals: overall, by_year, by_month, by_week, by_day."""
    overall = {
        "human": ZERO,
        "assistant": ZERO,
        "messages": {"human": 0, "assistant": 0},
        "conv_ids": set(),
    }
    by_year = defaultdict(
        lambda: {"human": ZERO, "assistant": ZERO, "messages": {"human": 0, "assistant": 0}, "conv_ids": set()}
    )
    by_month = defaultdict(
        lambda: {"human": ZERO, "assistant": ZERO, "messages": {"human": 0, "assistant": 0}, "conv_ids": set()}
    )
    by_week = defaultdict(
        lambda: {"human": ZERO, "assistant": ZERO, "messages": {"human": 0, "assistant": 0}, "conv_ids": set()}
    )
    by_day = defaultdict(
        lambda: {"human": ZERO, "assistant": ZERO, "messages": {"human": 0, "assistant": 0}, "conv_ids": set()}
    )

    for r in records:
        role = r["role"]
        vol = (r["words"], r["chars"])
        date = datetime.strptime(r["date"], "%Y-%m-%d")
        year = r["date"][:4]
        month = r["date"][:7]
        week = f"{date.isocalendar()[0]}-W{date.isocalendar()[1]:02d}"
        day = r["date"]

        for bucket, key in [
            (overall, None),
            (by_year, year),
            (by_month, month),
            (by_week, week),
            (by_day, day),
        ]:
            target = bucket if key is None else bucket[key]
            target[role] = add(target[role], vol)
            target["messages"][role] += 1
            target["conv_ids"].add(r["conv_id"])

    overall["conversations"] = len(overall.pop("conv_ids"))
    for d in [by_year, by_month, by_week, by_day]:
        for bucket in d.values():
            bucket["conversations"] = len(bucket.pop("conv_ids"))

    return {
        "overall": overall,
        "by_year": dict(sorted(by_year.items())),
        "by_month": dict(sorted(by_month.items())),
        "by_week": dict(sorted(by_week.items())),
        "by_day": dict(sorted(by_day.items())),
    }


# ---------- FORMATTING ----------

COL_W = 12


def fmt_num(n: int) -> str:
    return f"{n:>{COL_W},}"


def header_row() -> str:
    return f"{'':22}{'Messages':>{COL_W}}{'Words':>{COL_W}}{'Characters':>{COL_W}}"


def data_row(label: str, msgs: int, words: int, chars: int) -> str:
    return f"  {label:<20}{fmt_num(msgs)}{fmt_num(words)}{fmt_num(chars)}"


def print_block(title: str, bucket: dict):
    chats = bucket.get("conversations", 0)
    print(f"\n{title}  ({chats:,} chats)")
    print(header_row())
    h_msgs = bucket["messages"].get("human", 0)
    h_vol = bucket.get("human", ZERO)
    ai_msgs = bucket["messages"].get("assistant", 0)
    ai_vol = bucket.get("assistant", ZERO)
    print(data_row("User", h_msgs, h_vol[0], h_vol[1]))
    print(data_row("AI", ai_msgs, ai_vol[0], ai_vol[1]))


# ---------- MAIN ----------


def main():
    parser = argparse.ArgumentParser(description="Show message volume statistics from ChatGPT and/or Claude export files.")
    parser.add_argument("files", nargs="+", metavar="FILE", help="JSON export file(s)")
    parser.add_argument("--timezone", default=None, metavar="TIMEZONE", help="Timezone for timestamps (e.g. 'America/New_York'). Defaults to system timezone.")
    parser.add_argument("--start-date", default=None, metavar="YYYY-MM-DD", help="Ignore messages before this date")
    parser.add_argument("--end-date", default=None, metavar="YYYY-MM-DD", help="Ignore messages after this date")
    a = parser.parse_args()

    tz = resolve_timezone(a.timezone)

    all_records = []
    source_labels = []
    conversations_total = 0

    for arg in a.files:
        path = Path(arg)
        records, fmt, n_convs = detect_and_parse(path, tz)
        conversations_total += n_convs
        all_records.extend(records)
        source_labels.append(f"{path.name} ({fmt})")

    if a.start_date:
        all_records = [r for r in all_records if r["date"] >= a.start_date]
        print(f"Filtered to messages on or after {a.start_date} ({len(all_records)} records)")
    if a.end_date:
        all_records = [r for r in all_records if r["date"] <= a.end_date]
        print(f"Filtered to messages on or before {a.end_date} ({len(all_records)} records)")

    agg = aggregate(all_records)

    print("=" * 60)
    print("  AI Usage Statistics")
    print("=" * 60)
    print(f"  Sources:       {', '.join(source_labels)}")
    print(f"  Conversations: {conversations_total:,}")
    total_msgs = agg["overall"]["messages"].get("human", 0) + agg["overall"]["messages"].get("assistant", 0)
    print(f"  Messages:      {total_msgs:,}")
    print(f"  Active days:   {len(agg['by_day']):,}")

    print_block("--- Overall ---", agg["overall"])

    print("\n--- By Year ---")
    for year, bucket in agg["by_year"].items():
        print_block(year, bucket)

    print("\n--- By Month ---")
    for month, bucket in agg["by_month"].items():
        print_block(month, bucket)

    print("\n--- By Week ---")
    for week, bucket in agg["by_week"].items():
        print_block(week, bucket)

    print("\n--- By Day ---")
    for day, bucket in agg["by_day"].items():
        print_block(day, bucket)


if __name__ == "__main__":
    main()
