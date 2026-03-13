# chatlog-tools

Tools for converting AI conversation exports to browsable HTML files.

---

## chatgpt_export_to_html.py

Converts a ChatGPT `conversations.json` export into HTML files, one per conversation, plus an index.

### Quick start

1. Go to [chatgpt.com](https://chatgpt.com/) -> Settings -> Data controls -> **Export data**
2. Download and unzip the archive
3. Download `chatgpt_export_to_html.py` and `requirements.txt` from this repo
4. Run:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   python3 chatgpt_export_to_html.py conversations.json
   ```
5. Open `chatgpt_html_files/index_chatgpt.html` in your browser

### Returning users

```bash
source .venv/bin/activate
python3 chatgpt_export_to_html.py conversations.json
```

### Options

```
python3 chatgpt_export_to_html.py conversations.json [output_dir] [options]

positional arguments:
  conversations.json    ChatGPT export file
  output_dir            Output directory (default: <input_dir>/chatgpt_html_files)

options:
  --timezone TIMEZONE   Timezone for message timestamps (default: system timezone)
                        Examples:
                          --timezone "America/Los_Angeles"   (San Francisco)
                          --timezone "America/New_York"      (New York)
                          --timezone "Europe/Berlin"         (Berlin)
                          --timezone "Europe/London"         (London)

  --conversation-only   Output only user and assistant messages,
                        no metadata or tool calls
```

---

## claude_export_to_html.py

Converts an Anthropic/Claude `conversations.json` export into HTML files, one per conversation, plus an index. Preserves rich content including thinking blocks, tool use, and tool results.

### Setup

**First time:**
```bash
python3 -m venv .venv           # create virtual environment (one-time)
source .venv/bin/activate       # activate it
pip install -r requirements.txt # install dependencies (one-time)
```

**Next time:**
```bash
source .venv/bin/activate       # activate the environment
```

### Usage

```bash
python3 claude_export_to_html.py conversations.json
```

Output is written to `claude_html_files/` next to the input file by default.

### Options

```
python3 claude_export_to_html.py conversations.json [output_dir] [options]

positional arguments:
  conversations.json    Claude export file
  output_dir            Output directory (default: <input_dir>/claude_html_files)

options:
  --timezone TIMEZONE   Timezone for message timestamps (default: system timezone)
                        Examples:
                          --timezone "America/Los_Angeles"   (San Francisco)
                          --timezone "America/New_York"      (New York)
                          --timezone "Europe/Berlin"         (Berlin)
                          --timezone "Europe/London"         (London)

  --conversation-only   Output only user and assistant messages,
                        no metadata or tool calls
```

### How to export your Claude data

1. Go to [claude.ai](https://claude.ai/) -> Settings -> Privacy
2. Click **Export data**
3. Download and unzip the archive
4. Run the script on the `conversations.json` file inside
