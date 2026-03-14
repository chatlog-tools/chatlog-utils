# chatlog-tools

Tools for converting AI conversation exports to browsable HTML files.

---

## chatgpt_export_to_html.py

Converts a ChatGPT `conversations.json` export into HTML and/or Markdown files, one per conversation, plus an index.

Output structure:
```
<output_dir>/
├── index_chatgpt.html        (HTML format)
├── index_chatgpt.md          (Markdown format)
├── chatgpt_html_files/
│   └── <conversation-id>.html
└── chatgpt_md_files/
    └── <conversation-id>.md
```

Re-running is safe: existing conversations in the index are preserved even if they are no longer in the new export (e.g. because you deleted them from your ChatGPT account). New conversations are added and existing ones are refreshed.

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
5. Open `index_chatgpt.html` in your browser

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
  output_dir            Output directory (default: same directory as input file).
                        Conversation files go in a chatgpt_html_files/ or chatgpt_md_files/
                        subfolder; the index goes directly in this directory.

options:
  --format FORMAT       Output format (default: html)
                          html      → chatgpt_html_files/  (one .html per conversation)
                          markdown  → chatgpt_md_files/    (one .md  per conversation)
                          both      → both directories in one run
                        Markdown output is always conversation-only.

  --timezone TIMEZONE   Timezone for message timestamps (default: system timezone)
                        Examples:
                          --timezone "America/Los_Angeles"   (San Francisco)
                          --timezone "America/New_York"      (New York)
                          --timezone "Europe/Berlin"         (Berlin)
                          --timezone "Europe/London"         (London)

  --conversation-only   Output only user and assistant messages,
                        no metadata or tool calls (HTML only)
```

---

## claude_export_to_html.py

Converts an Anthropic/Claude `conversations.json` export into HTML and/or Markdown files, one per conversation, plus an index. Preserves rich content including thinking blocks, tool use, and tool results (HTML only).

Output structure:
```
<output_dir>/
├── index_claude.html         (HTML format)
├── index_claude.md           (Markdown format)
├── claude_html_files/
│   └── <conversation-uuid>.html
└── claude_md_files/
    └── <conversation-uuid>.md
```

Re-running is safe: same incremental behavior as the ChatGPT script above.

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

### Options

```
python3 claude_export_to_html.py conversations.json [output_dir] [options]

positional arguments:
  conversations.json    Claude export file
  output_dir            Output directory (default: same directory as input file).
                        Conversation files go in a claude_html_files/ or claude_md_files/
                        subfolder; the index goes directly in this directory.

options:
  --format FORMAT       Output format (default: html)
                          html      → claude_html_files/  (one .html per conversation)
                          markdown  → claude_md_files/    (one .md  per conversation)
                          both      → both directories in one run
                        Markdown output is always conversation-only.

  --timezone TIMEZONE   Timezone for message timestamps (default: system timezone)
                        Examples:
                          --timezone "America/Los_Angeles"   (San Francisco)
                          --timezone "America/New_York"      (New York)
                          --timezone "Europe/Berlin"         (Berlin)
                          --timezone "Europe/London"         (London)

  --conversation-only   Output only user and assistant messages,
                        no metadata or tool calls (HTML only)
```

### How to export your Claude data

1. Go to [claude.ai](https://claude.ai/) -> Settings -> Privacy
2. Click **Export data**
3. Download and unzip the archive
4. Run the script on the `conversations.json` file inside

---

## split_json.py

Splits a `conversations.json` export into individual JSON files, one per conversation.

Useful if you want to inspect the raw data in a text editor. The full export file can easily be hundreds of MB, which crashes most editors. With this script, each conversation becomes its own small file you can open directly.

No dependencies beyond the Python standard library.

### Usage

```bash
python3 split_json.py conversations.json [output_dir]
```

Output goes to `split_conversations_json/` next to the input file by default.

---

## analysis/

Usage statistics and charts from ChatGPT and/or Claude export files. Both scripts accept multiple input files and auto-detect the format.

### usage_stats.py

Prints a text table of message counts, word counts, and character counts broken down by year, month, week, and day.

### plot_stats.py

Generates three self-contained interactive HTML files using Plotly:
- `usage_monthly.html`
- `usage_weekly.html`
- `usage_daily.html`

### Setup

**First time:**
```bash
python3 -m venv .venv           # create virtual environment (one-time)
source .venv/bin/activate       # activate it (if you haven't already)
pip install -r analysis/requirements.txt # (one-time)
```

**Next time:**
```bash
source .venv/bin/activate       # activate it (if you haven't already)
```

### Usage

```bash
python analysis/usage_stats.py file1.json [file2.json ...] [options]
python analysis/plot_stats.py  file1.json [file2.json ...] [options]

options:
  --timezone TIMEZONE        Timezone for timestamps (default: system timezone)
  --output-dir DIR           Output directory for HTML files (plot_stats.py only)
  --start-date YYYY-MM-DD    Ignore messages before this date
  --end-date   YYYY-MM-DD    Ignore messages after this date
```
