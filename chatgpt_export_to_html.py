import argparse
import html
import json
import sys
from datetime import datetime, timezone as dt_timezone
from pathlib import Path

import mistune
from pytz import timezone
from pytz.exceptions import UnknownTimeZoneError
from tzlocal import get_localzone


# ---------- CONFIGURATION ----------
ROLE_NAMES = {"user": "User", "assistant": "ChatGPT", "system": "System"}
_md = mistune.create_markdown()

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


def _render_part(part, clean=False) -> str:
    """Render a single message part (str or dict) to HTML. Returns empty string to skip."""
    if isinstance(part, str):
        return _md(part) if part.strip() else ""

    ct = part.get("content_type", "")

    if ct == "tether_browsing_display":
        if clean:
            return ""
        result = part.get("result", "")
        summary = part.get("summary", "")
        if not result and not summary:
            return ""
        label = html.escape(summary) if summary else "Web Search Result"
        style = "background-color: #e3f2fd; border-left: 4px solid #1e88e5; padding: 8px 12px; margin: 6px 0; font-size: 0.85em;"
        return (
            f'<details style="{style}">'
            f"<summary><strong>🌐 Web Search</strong> — {label}</summary>"
            f"<pre>{html.escape(result)}</pre>"
            f"</details>"
        )

    if ct == "audio_transcription":
        text = part.get("text", "")
        return _md(text) if text.strip() else ""

    if ct == "image_asset_pointer":
        return "<p><em>[Image]</em></p>"

    if ct == "audio_asset_pointer":
        return "<p><em>[Voice message]</em></p>"

    if ct == "real_time_user_audio_video_asset_pointer":
        return "<p><em>[Voice/Video message]</em></p>"

    # app_pairing_content and any other unknown types: skip
    return ""


def extract_messages(conversation, tz, clean=False):
    messages = []
    nodes = sorted(
        conversation.get("mapping", {}).values(),
        key=lambda n: (n.get("message") or {}).get("create_time") or 0,
    )
    for node in nodes:
        message = node.get("message")
        if not message:
            continue

        author_key = message.get("author", {}).get("role", "unknown")
        author = ROLE_NAMES.get(author_key, author_key.capitalize())

        if clean and author == "Tool":
            continue

        parts = message.get("content", {}).get("parts", [])
        rendered_parts = [r for part in parts if (r := _render_part(part, clean=clean))]
        if not rendered_parts:
            continue
        timestamp = to_local_str(message.get("create_time"), tz)

        message_type = (
            "voice"
            if message.get("metadata", {}).get("voice_mode_message")
            else "typed"
        )
        model = message.get("metadata", {}).get("model_slug", "ChatGPT")

        messages.append(
            {
                "author": author,
                "content": "\n".join(rendered_parts),
                "timestamp": timestamp,
                "type": message_type,
                "model": model,
            }
        )
    return messages


# ---------- MAIN SCRIPT ----------

GLOBAL_CSS = """
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 900px; margin: 0 auto; padding: 20px; line-height: 1.5; }
  h2 { border-bottom: 1px solid #ccc; padding-bottom: 8px; }
  pre { white-space: pre-wrap; word-wrap: break-word; }
  a { color: #1a73e8; }
</style>
"""



def main():
    parser = argparse.ArgumentParser(
        description="Converts ChatGPT export conversations.json to HTML files."
    )
    parser.add_argument("input", metavar="input_file.json", help="Input JSON export file")
    parser.add_argument("output_dir", nargs="?", help="Output directory (default: <input_dir>/chatgpt_html_files)")
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
    output_dir = Path(args.output_dir) if args.output_dir else input_path.parent / "chatgpt_html_files"
    output_dir.mkdir(parents=True, exist_ok=True)

    # Load JSON data
    with input_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    index_links = []

    for conversation in data:
        messages = extract_messages(conversation, tz, clean=args.conversation_only)
        if not messages:
            continue

        last_user_message = next(
            (msg for msg in reversed(messages) if msg["author"] == "User"), None
        )
        if not last_user_message:
            continue

        timestamp = last_user_message["timestamp"].split()[0]
        title = conversation.get("title", "chat")
        filename = f"{conversation.get('id', 'unknown')}.html"

        metadata_html = '<details style="background-color: #eef; padding: 10px; margin-bottom: 20px; border-radius: 4px;"><summary style="cursor: pointer;"><strong>Conversation Metadata</strong></summary>'
        conv_id = conversation.get("id", "")
        if conv_id:
            metadata_html += f"<p><strong>ID:</strong> <code>{html.escape(conv_id)}</code></p>"
        custom_gpt = conversation.get("gpt_metadata", {}).get("display_name")
        if custom_gpt:
            metadata_html += (
                f"<p><strong>Custom GPT:</strong> {html.escape(custom_gpt)}</p>"
            )
        project_name = conversation.get("workspace_metadata", {}).get("name")
        if project_name:
            metadata_html += f"<p><strong>Project:</strong> {html.escape(project_name)}</p>"

        for node in conversation.get("mapping", {}).values():
            message = node.get("message")
            if not message:
                continue
            content = message.get("content")
            if not content:
                continue
            if content.get("content_type") == "user_editable_context":
                user_profile = content.get("user_profile")
                user_instructions = content.get("user_instructions")
                if user_profile:
                    metadata_html += f"<p><strong>User Profile:</strong><pre>{html.escape(user_profile)}</pre></p>"
                if user_instructions:
                    metadata_html += f"<p><strong>User Instructions:</strong> {html.escape(user_instructions)}</p>"
        metadata_html += "</details>"

        html_content = f'<!DOCTYPE html><html><head><meta charset="UTF-8"><title>{html.escape(title)}</title>{GLOBAL_CSS}</head><body>'
        html_content += f"<h2>{html.escape(title)}</h2>"
        if not args.conversation_only:
            html_content += metadata_html
        for message in messages:
            if message["author"] == "Tool":
                style = "background-color: #e8f5e9; border-left: 4px solid #43a047; padding: 8px 12px; margin: 6px 0; font-size: 0.85em;"
                html_content += (
                    f'<details style="{style}">'
                    f'<summary style="cursor: pointer;"><strong>🔧 Tool</strong> <span style="color: #888; font-size: 0.85em;">at {message["timestamp"]}</span></summary>'
                    f'{message["content"]}'
                    f"</details>"
                )
            else:
                color = "#f0f0f0" if message["author"] == "User" else "#ffffff"
                border = "border: 1px solid #ddd; border-radius: 4px;"
                html_content += f'<div style="background-color: {color}; padding: 12px; margin: 8px 0; {border}">'
                html_content += f'<p style="margin-top: 0;"><strong>{message["author"]}</strong> <span style="color: #888; font-size: 0.85em;">({message["type"]}, {message["model"]}) at {message["timestamp"]}</span></p>'
                html_content += message["content"]
                html_content += "</div>"
        html_content += "</body></html>"

        output_file = output_dir / filename
        with output_file.open("w", encoding="utf-8") as f:
            f.write(html_content)
        print(f"Saved: {output_file.name}")
        sort_key = conversation.get("update_time", 0)
        index_links.append(
            (sort_key, f'<li><a href="{output_file.name}">{html.escape(title)} ({timestamp})</a></li>')
        )

    # Generate index.html
    if index_links:
        index_links.sort(key=lambda x: x[0], reverse=True)
        index_path = output_dir / "index_chatgpt.html"
        with index_path.open("w", encoding="utf-8") as f:
            f.write(f'<!DOCTYPE html><html><head><meta charset="UTF-8"><title>ChatGPT Chat Index</title>{GLOBAL_CSS}</head><body>')
            f.write(f"<h1>ChatGPT Chat Index</h1><p>{len(index_links)} conversations</p><ul>")
            f.write("\n".join(link for _, link in index_links))
            f.write("</ul></body></html>")
        print(f"Index written to: {index_path.name}")


if __name__ == "__main__":
    main()
