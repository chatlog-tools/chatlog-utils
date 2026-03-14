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


def render_content_blocks(content_blocks, clean=False, fmt="html"):
    """Render content blocks into HTML or markdown text."""
    parts = []

    for block in content_blocks:
        if not isinstance(block, dict):
            continue

        block_type = block.get("type", "")

        # Markdown is always conversation-only: skip thinking, tool_use, tool_result
        if fmt == "markdown" and block_type in {"thinking", "tool_use", "tool_result"}:
            continue
        if clean and block_type in {"thinking", "tool_use", "tool_result"}:
            continue

        if block_type == "thinking":
            thinking_text = block.get("thinking", "")
            if not thinking_text.strip():
                continue
            style = BLOCK_STYLES["thinking"]
            label = BLOCK_LABELS["thinking"]
            summaries = block.get("summaries", [])
            summary_hint = ""
            if summaries:
                summary_texts = [s.get("summary", "") for s in summaries if s.get("summary")]
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

            result_text = ""
            result_content = block.get("content", [])
            if isinstance(result_content, list):
                for item in result_content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        result_text += item.get("text", "")

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
                parts.append(_md(text) if fmt == "html" else text.strip())

        else:
            # Unknown block type - render what we can
            text = block.get("text", "") or block.get("content", "")
            if isinstance(text, str) and text.strip():
                if fmt == "html":
                    parts.append(f"<div><em>[{html.escape(block_type)}]</em> {_md(text)}</div>")
                else:
                    parts.append(f"*[{block_type}]* {text.strip()}")

    return "\n".join(parts)


def extract_messages(conversation, tz, clean=False, fmt="html"):
    """Extract messages from a Claude conversation, preserving content block structure."""
    messages = []
    chat_messages = conversation.get("chat_messages", [])

    for msg in chat_messages:
        content_blocks = msg.get("content", [])
        sender = msg.get("sender", "unknown")
        author = ROLE_NAMES.get(sender, sender.capitalize())
        timestamp = to_local_str(msg.get("created_at"), tz)

        if isinstance(content_blocks, list) and content_blocks:
            rendered = render_content_blocks(content_blocks, clean=clean, fmt=fmt)
        else:
            text = msg.get("text", "")
            if not text.strip():
                continue
            rendered = _md(text) if fmt == "html" else text.strip()

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
    """Parse an existing HTML index file and return a dict of {uuid: (date_str, li_html)}."""
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


def load_existing_md_index(index_path):
    """Parse an existing markdown index file and return a dict of {uuid: (date_str, line)}."""
    if not index_path.exists():
        return {}
    content = index_path.read_text(encoding="utf-8")
    entries = {}
    for line in re.findall(r'- \[.*?\]\(.*?\)', content):
        uuid_match = re.search(r'\(([a-f0-9-]{36})\)', line)
        date_match = re.search(r'\[(\d{4}-\d{2}-\d{2})\s', line)
        if uuid_match and date_match:
            entries[uuid_match.group(1)] = (date_match.group(1), line)
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
        description="Converts Anthropic/Claude data export conversations.json to HTML and/or Markdown files."
    )
    parser.add_argument("input", metavar="conversations.json", help="Input JSON export file")
    parser.add_argument(
        "output_dir",
        nargs="?",
        help=(
            "Output directory (default: same directory as input file). "
            "Conversation files go in a claude_html_files/ or claude_md_files/ subfolder; "
            "the index goes directly in this directory."
        ),
    )
    parser.add_argument("--timezone", default=None, help="Timezone name (e.g. 'America/New_York'). Defaults to system timezone.")
    parser.add_argument("--conversation-only", action="store_true", help="Output only user and assistant messages, no metadata or tool calls. HTML only; markdown is always conversation-only.")
    parser.add_argument(
        "--format",
        choices=["html", "markdown", "both"],
        default="html",
        metavar="FORMAT",
        help="Output format: html (default), markdown, or both. Markdown is always conversation-only.",
    )
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
    fmt = args.format

    html_conv_dir = base_dir / "claude_html_files"
    html_index_path = base_dir / "index_claude.html"
    md_conv_dir = base_dir / "claude_md_files"
    md_index_path = base_dir / "index_claude.md"

    if fmt in ("html", "both"):
        html_conv_dir.mkdir(parents=True, exist_ok=True)
    if fmt in ("markdown", "both"):
        md_conv_dir.mkdir(parents=True, exist_ok=True)

    with input_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    print(f"Loaded {len(data)} conversations from {input_path.name}")

    existing_html_entries = load_existing_index(html_index_path) if fmt in ("html", "both") else {}
    existing_md_entries = load_existing_md_index(md_index_path) if fmt in ("markdown", "both") else {}
    new_html_entries = {}
    new_md_entries = {}
    skipped = 0

    for conversation in data:
        conv_uuid = conversation.get("uuid", "unknown")
        title = conversation.get("name", "") or "Untitled Chat"
        updated_at = conversation.get("updated_at", "")
        date_str = to_local_str(updated_at, tz).split()[0] if updated_at else "0000-00-00"
        has_output = False

        # --- HTML output ---
        if fmt in ("html", "both"):
            messages = extract_messages(conversation, tz, clean=args.conversation_only, fmt="html")
            if messages and any(m["author"] == "User" for m in messages):
                has_output = True
                filename = f"{conv_uuid}.html"

                metadata_html = '<details style="background-color: #eef; padding: 10px; margin-bottom: 20px; border-radius: 4px;"><summary style="cursor: pointer;"><strong>Conversation Metadata</strong></summary>'
                if conv_uuid:
                    metadata_html += f"<p><strong>UUID:</strong> <code>{html.escape(conv_uuid)}</code></p>"
                created = to_local_str(conversation.get("created_at"), tz)
                updated = to_local_str(conversation.get("updated_at"), tz)
                metadata_html += f"<p><strong>Created:</strong> {html.escape(created)}</p>"
                metadata_html += f"<p><strong>Updated:</strong> {html.escape(updated)}</p>"
                account = conversation.get("account", {})
                if account and isinstance(account, dict):
                    acc_uuid = account.get("uuid", "")
                    if acc_uuid:
                        metadata_html += f"<p><strong>Account:</strong> <code>{html.escape(acc_uuid)}</code></p>"
                project = conversation.get("project")
                if project and isinstance(project, dict):
                    project_name = project.get("name", "")
                    if project_name:
                        metadata_html += f"<p><strong>Project:</strong> {html.escape(project_name)}</p>"
                summary = conversation.get("summary", "")
                if summary and summary.strip():
                    metadata_html += f'<div style="margin-top: 8px; padding: 8px; background: #e8eaf6; border-radius: 4px;"><strong>Summary:</strong><br>{_md(summary)}</div>'
                metadata_html += "</details>"

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

                output_file = html_conv_dir / filename
                output_file.write_text(html_content, encoding="utf-8")
                print(f"Saved: {output_file.name}")

                link_text = f"{date_str} {title} ({conv_uuid})"
                href = f"claude_html_files/{filename}"
                new_html_entries[conv_uuid] = (date_str, f'<li><a href="{href}">{html.escape(link_text)}</a></li>')

        # --- Markdown output ---
        if fmt in ("markdown", "both"):
            messages = extract_messages(conversation, tz, clean=True, fmt="markdown")
            if messages and any(m["author"] == "User" for m in messages):
                has_output = True
                filename = f"{conv_uuid}.md"

                lines = [f"# {title}", "", f"*UUID: {conv_uuid}*", "", "---", ""]
                for message in messages:
                    lines.append(f"**{message['author']}** — {message['timestamp']}")
                    lines.append("")
                    lines.append(message["content"])
                    lines.append("")
                    lines.append("---")
                    lines.append("")

                output_file = md_conv_dir / filename
                output_file.write_text("\n".join(lines), encoding="utf-8")
                print(f"Saved: {output_file.name}")

                link_text = f"{date_str} {title} ({conv_uuid})"
                href = f"claude_md_files/{filename}"
                new_md_entries[conv_uuid] = (date_str, f"- [{link_text}]({href})")

        if not has_output:
            skipped += 1

    # Write HTML index
    if fmt in ("html", "both"):
        merged = {**existing_html_entries, **new_html_entries}
        merged = {uid: v for uid, v in merged.items() if (html_conv_dir / f"{uid}.html").exists()}
        sorted_entries = sorted(merged.values(), key=lambda x: x[0], reverse=True)
        if sorted_entries:
            with html_index_path.open("w", encoding="utf-8") as f:
                f.write(f'<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Claude Chat Index</title>{GLOBAL_CSS}</head><body>')
                f.write(f"<h1>Claude Chat Index</h1><p>{len(sorted_entries)} conversations</p><ul>")
                f.write("\n".join(li for _, li in sorted_entries))
                f.write("</ul></body></html>")
            print(f"\nIndex written to: {html_index_path}")

    # Write Markdown index
    if fmt in ("markdown", "both"):
        merged = {**existing_md_entries, **new_md_entries}
        merged = {uid: v for uid, v in merged.items() if (md_conv_dir / f"{uid}.md").exists()}
        sorted_entries = sorted(merged.values(), key=lambda x: x[0], reverse=True)
        if sorted_entries:
            with md_index_path.open("w", encoding="utf-8") as f:
                f.write(f"# Claude Chat Index\n\n{len(sorted_entries)} conversations\n\n")
                f.write("\n".join(line for _, line in sorted_entries))
                f.write("\n")
            print(f"\nIndex written to: {md_index_path}")

    total = max(len(new_html_entries), len(new_md_entries))
    print(f"\nDone: {total} conversations exported, {skipped} skipped (empty/no user messages)")


if __name__ == "__main__":
    main()
