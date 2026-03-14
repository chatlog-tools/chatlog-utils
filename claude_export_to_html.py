import argparse
import html
import json
import re
import sys
from datetime import datetime, timezone as dt_timezone
from pathlib import Path

import mistune
from pytz import timezone
from pytz.exceptions import UnknownTimeZoneError
from tzlocal import get_localzone

_md = mistune.create_markdown()

# ---------- CONFIGURATION ----------
ROLE_NAMES = {"human": "User", "assistant": "Claude", "system": "System"}

# Colors/styles for different content block types
BLOCK_STYLES = {
    "text": "",  # inherits from message div
    "thinking": "background-color: #fff8e1; border-left: 4px solid #ffb300; padding: 8px 12px; margin: 6px 0; font-style: italic; color: #5d4037;",
    "tool_use": "background-color: #e8f5e9; border-left: 4px solid #43a047; padding: 8px 12px; margin: 6px 0; font-family: monospace; font-size: 0.9em;",
    "tool_result": "background-color: #e3f2fd; border-left: 4px solid #1e88e5; padding: 8px 12px; margin: 6px 0; font-family: monospace; font-size: 0.85em; max-height: 300px; overflow-y: auto;",
}

BLOCK_LABELS = {
    "thinking": "\U0001f4ad Thinking",
    "tool_use": "\U0001f527 Tool Use",
    "tool_result": "\U0001f4cb Tool Result",
}

# ---------- HELPER FUNCTIONS ----------

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


def to_local_str(timestamp, tz) -> str:
    """Convert a Unix float or ISO 8601 string to 'YYYY-MM-DD HH:MM:SS' in local time."""
    if timestamp is None:
        return "Unknown time"
    try:
        return _to_utc(timestamp).astimezone(tz).strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError, OSError):
        return f"Unknown time ({timestamp})"


def render_content_blocks(content_blocks, clean=False):
    """Render content blocks into HTML, distinguishing thinking, tool use, tool results, and text."""
    parts = []

    for block in content_blocks:
        if not isinstance(block, dict):
            continue

        block_type = block.get("type", "")

        if clean and block_type in {"thinking", "tool_use", "tool_result"}:
            continue


        if block_type == "thinking":
            thinking_text = block.get("thinking", "")
            if not thinking_text.strip():
                continue
            style = BLOCK_STYLES["thinking"]
            label = BLOCK_LABELS["thinking"]
            # Render summaries if present
            summaries = block.get("summaries", [])
            summary_hint = ""
            if summaries:
                summary_texts = [
                    s.get("summary", "") for s in summaries if s.get("summary")
                ]
                if summary_texts:
                    summary_hint = f" — {html.escape(summary_texts[0])}"
            parts.append(
                f'<details style="{style}">'
                f"<summary><strong>{label}</strong>{summary_hint}</summary>"
                f"{_md(thinking_text)}"
                f"</details>"
            )

        elif block_type == "tool_use":
            tool_name = block.get("name", "unknown")
            tool_input = block.get("input", {})
            integration = block.get("integration_name", "")
            message = block.get("message", "")
            style = BLOCK_STYLES["tool_use"]
            label = BLOCK_LABELS["tool_use"]

            input_str = (
                json.dumps(tool_input, indent=2, ensure_ascii=False)
                if tool_input
                else ""
            )

            header = f"{tool_name}"
            if integration:
                header += f" ({html.escape(integration)})"

            parts.append(
                f'<details style="{style}">'
                f"<summary><strong>{label}: {html.escape(header)}</strong>"
                f"{f' — <em>{html.escape(message)}</em>' if message else ''}"
                f"</summary>"
                f"{f'<pre>{html.escape(input_str)}</pre>' if input_str else ''}"
                f"</details>"
            )

        elif block_type == "tool_result":
            tool_name = block.get("name", "unknown")
            is_error = block.get("is_error", False)
            message = block.get("message", "")
            style = BLOCK_STYLES["tool_result"]
            label = BLOCK_LABELS["tool_result"]

            # Extract text from content array
            result_text = ""
            result_content = block.get("content", [])
            if isinstance(result_content, list):
                for item in result_content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        result_text += item.get("text", "")

            # Show display_content titles if available
            display = block.get("display_content", {})
            display_items = ""
            if display and isinstance(display, dict):
                items = display.get("content", [])
                if items:
                    display_items = (
                        "<ul>"
                        + "".join(
                            f'<li><a href="{html.escape(it.get("url") or "")}">{html.escape(it.get("title") or "Untitled")}</a></li>'
                            for it in items
                            if isinstance(it, dict)
                        )
                        + "</ul>"
                    )

            error_flag = " \u26a0\ufe0f ERROR" if is_error else ""

            # Truncate very long tool results
            if len(result_text) > 2000:
                result_text = result_text[:2000] + "\n... [truncated]"

            parts.append(
                f'<details style="{style}">'
                f"<summary><strong>{label}: {html.escape(tool_name)}{error_flag}</strong>"
                f"{f' — <em>{html.escape(message)}</em>' if message else ''}"
                f"</summary>"
                f"{display_items}"
                f"{f'<pre>{html.escape(result_text)}</pre>' if result_text else ''}"
                f"</details>"
            )

        elif block_type == "text":
            text = block.get("text", "")
            if text.strip():
                parts.append(_md(text))

        else:
            # Unknown block type - render what we can
            text = block.get("text", "") or block.get("content", "")
            if isinstance(text, str) and text.strip():
                parts.append(
                    f"<div><em>[{html.escape(block_type)}]</em> {_md(text)}</div>"
                )

    return "\n".join(parts)


def extract_messages(conversation, tz, clean=False):
    """Extract messages from a Claude conversation, preserving content block structure."""
    messages = []
    chat_messages = conversation.get("chat_messages", [])

    for msg in chat_messages:
        content_blocks = msg.get("content", [])
        sender = msg.get("sender", "unknown")
        author = ROLE_NAMES.get(sender, sender.capitalize())
        timestamp = to_local_str(msg.get("created_at"), tz)

        # Render structured content blocks (thinking, tool_use, tool_result, text)
        if isinstance(content_blocks, list) and content_blocks:
            rendered = render_content_blocks(content_blocks, clean=clean)
        else:
            # Fallback to plain text field
            text = msg.get("text", "")
            if not text.strip():
                continue
            rendered = _md(text)

        if not rendered.strip():
            continue

        messages.append(
            {
                "author": author,
                "content": rendered,
                "timestamp": timestamp,
            }
        )

    return messages


def load_existing_index(index_path):
    """Parse an existing index HTML file and return a dict of {uuid: (date_str, li_html)}."""
    if not index_path.exists():
        return {}
    content = index_path.read_text(encoding="utf-8")
    entries = {}
    for li in re.findall(r'<li>.*?</li>', content):
        uuid_match = re.search(r'\(([a-f0-9-]{36})\)</a>', li)
        date_match = re.search(r'>(\d{4}-\d{2}-\d{2})\s', li)
        if uuid_match and date_match:
            entries[uuid_match.group(1)] = (date_match.group(1), li)
    return entries


# ---------- MAIN SCRIPT ----------

GLOBAL_CSS = """
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 900px; margin: 0 auto; padding: 20px; line-height: 1.5; }
  h2 { border-bottom: 1px solid #ccc; padding-bottom: 8px; }
  pre { white-space: pre-wrap; word-wrap: break-word; }
  details summary { cursor: pointer; color: #555; font-size: 0.9em; }
  details summary strong { color: #333; }
  details { margin: 6px 0; }
  a { color: #1a73e8; }
</style>
"""


def main():
    parser = argparse.ArgumentParser(
        description="Converts Anthropic/Claude data export conversations.json to HTML files."
    )
    parser.add_argument("input", metavar="conversations.json", help="Input JSON export file")
    parser.add_argument(
        "output_dir",
        nargs="?",
        help=(
            "Output directory (default: same directory as input file). "
            "Conversation files go in a claude_html_files/ subfolder; "
            "the index goes directly in this directory."
        ),
    )
    parser.add_argument("--timezone", default=None, help="Timezone name (e.g. 'America/New_York'). Defaults to system timezone.")
    parser.add_argument("--conversation-only", action="store_true", help="Output only user and assistant messages, no metadata or tool calls.")
    args = parser.parse_args()

    if args.timezone:
        try:
            tz = timezone(args.timezone)
        except UnknownTimeZoneError:
            print(f'Error: Unknown timezone "{args.timezone}". Please use a timezone name like one of these:')
            print('  --timezone "America/Los_Angeles"   (San Francisco / Pacific Time)')
            print('  --timezone "America/New_York"      (New York / Eastern Time)')
            print('  --timezone "Europe/Berlin"         (Berlin / Central European Time)')
            print('  --timezone "Europe/London"         (London / GMT)')
            print()
            print("To use your computer's local timezone (the default), just omit the --timezone flag.")
            sys.exit(1)
    else:
        tz = get_localzone()

    input_path = Path(args.input)
    base_dir = Path(args.output_dir) if args.output_dir else input_path.parent
    conv_dir = base_dir / "claude_html_files"
    index_path = base_dir / "index_claude.html"
    conv_dir.mkdir(parents=True, exist_ok=True)

    with input_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    print(f"Loaded {len(data)} conversations from {input_path.name}")

    # Load existing index entries (for incremental updates)
    existing_entries = load_existing_index(index_path)
    new_entries = {}
    skipped = 0

    for conversation in data:
        messages = extract_messages(conversation, tz, clean=args.conversation_only)
        if not messages:
            skipped += 1
            continue

        last_user_message = next(
            (msg for msg in reversed(messages) if msg["author"] == "User"), None
        )
        if not last_user_message:
            skipped += 1
            continue

        conv_uuid = conversation.get("uuid", "unknown")
        title = conversation.get("name", "") or "Untitled Chat"
        filename = f"{conv_uuid}.html"

        # Build metadata section
        metadata_html = '<details style="background-color: #eef; padding: 10px; margin-bottom: 20px; border-radius: 4px;"><summary style="cursor: pointer;"><strong>Conversation Metadata</strong></summary>'

        if conv_uuid:
            metadata_html += (
                f"<p><strong>UUID:</strong> <code>{html.escape(conv_uuid)}</code></p>"
            )

        created = to_local_str(conversation.get("created_at"), tz)
        updated = to_local_str(conversation.get("updated_at"), tz)
        metadata_html += f"<p><strong>Created:</strong> {html.escape(created)}</p>"
        metadata_html += f"<p><strong>Updated:</strong> {html.escape(updated)}</p>"

        # Account info
        account = conversation.get("account", {})
        if account and isinstance(account, dict):
            acc_uuid = account.get("uuid", "")
            if acc_uuid:
                metadata_html += (
                    f"<p><strong>Account:</strong> <code>{html.escape(acc_uuid)}</code></p>"
                )

        # Project info
        project = conversation.get("project")
        if project and isinstance(project, dict):
            project_name = project.get("name", "")
            if project_name:
                metadata_html += (
                    f"<p><strong>Project:</strong> {html.escape(project_name)}</p>"
                )

        # Summary
        summary = conversation.get("summary", "")
        if summary and summary.strip():
            metadata_html += f'<div style="margin-top: 8px; padding: 8px; background: #e8eaf6; border-radius: 4px;"><strong>Summary:</strong><br>{_md(summary)}</div>'

        metadata_html += "</details>"

        # Build full HTML
        html_content = f'<!DOCTYPE html><html><head><meta charset="UTF-8"><title>{html.escape(title)}</title>{GLOBAL_CSS}</head><body>'
        html_content += f"<h2>{html.escape(title)}</h2>"
        if not args.conversation_only:
            html_content += metadata_html

        for message in messages:
            color = "#f0f0f0" if message["author"] == "User" else "#ffffff"
            border = "border: 1px solid #ddd; border-radius: 4px;"
            html_content += f'<div style="background-color: {color}; padding: 12px; margin: 8px 0; {border}">'
            html_content += f'<p style="margin-top: 0;"><strong>{message["author"]}</strong> <span style="color: #888; font-size: 0.85em;">at {message["timestamp"]}</span></p>'
            html_content += message["content"]
            html_content += "</div>"

        html_content += "</body></html>"

        output_file = conv_dir / filename
        with output_file.open("w", encoding="utf-8") as f:
            f.write(html_content)
        print(f"Saved: {output_file.name}")

        updated_at = conversation.get("updated_at", "")
        date_str = to_local_str(updated_at, tz).split()[0] if updated_at else "0000-00-00"
        link_text = f"{date_str} {title} ({conv_uuid})"
        href = f"claude_html_files/{filename}"
        new_entries[conv_uuid] = (date_str, f'<li><a href="{href}">{html.escape(link_text)}</a></li>')

    # Merge: existing entries + new entries (new wins on collision)
    merged = {**existing_entries, **new_entries}
    # Remove entries whose HTML file no longer exists on disk
    merged = {uid: v for uid, v in merged.items() if (conv_dir / f"{uid}.html").exists()}
    # Sort by date descending
    sorted_entries = sorted(merged.values(), key=lambda x: x[0], reverse=True)

    if sorted_entries:
        with index_path.open("w", encoding="utf-8") as f:
            f.write(
                f'<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Claude Chat Index</title>{GLOBAL_CSS}</head><body>'
            )
            f.write(
                f"<h1>Claude Chat Index</h1><p>{len(sorted_entries)} conversations</p><ul>"
            )
            f.write("\n".join(li for _, li in sorted_entries))
            f.write("</ul></body></html>")
        print(f"\nIndex written to: {index_path}")

    print(
        f"\nDone: {len(new_entries)} conversations exported, {skipped} skipped (empty/no user messages)"
    )


if __name__ == "__main__":
    main()
