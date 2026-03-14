"""Plot AI usage statistics as interactive charts (Plotly).

Usage:
  python3 plot_stats.py <file1.json> [file2.json ...] [--output-dir <dir>] [--start-date YYYY-MM-DD] [--end-date YYYY-MM-DD]

Produces three self-contained HTML files:
  usage_monthly.html — Messages, words, and user word-share % by month
  usage_weekly.html  — Same charts by ISO week
  usage_daily.html   — Same charts by day
"""

import argparse
from pathlib import Path
import sys
from datetime import date, timedelta

try:
    import plotly.graph_objects as go
except ImportError:
    print("plotly is not installed. Run: pip install plotly")
    sys.exit(1)

from usage_stats import detect_and_parse, aggregate, resolve_timezone

ZERO = (0, 0)

# ---------- HELPERS ----------


def all_weeks_between(first: str, last: str) -> list[str]:
    """Return every ISO week label (YYYY-Www) from first to last inclusive."""

    def parse_week(w: str) -> date:
        year, wnum = int(w[:4]), int(w[6:])
        return date.fromisocalendar(year, wnum, 1)  # Monday

    d = parse_week(first)
    end = parse_week(last)
    weeks = []
    while d <= end:
        iso = d.isocalendar()
        weeks.append(f"{iso[0]}-W{iso[1]:02d}")
        d += timedelta(weeks=1)
    return weeks


def week_to_wednesday(w: str) -> str:
    """Convert 'YYYY-Www' to the ISO date string of Wednesday of that week."""
    year, wnum = int(w[:4]), int(w[6:])
    return date.fromisocalendar(year, wnum, 3).isoformat()


def bucket_series(
    agg_bucket: dict, fill_weeks: bool = False
) -> tuple[list, list, list, list, list]:
    """Extract parallel lists (labels, user_msgs, ai_msgs, user_words, ai_words) from a bucket dict.
    If fill_weeks=True, insert zero-valued entries for any missing weeks in the range."""
    if fill_weeks and agg_bucket:
        keys = sorted(agg_bucket.keys())
        all_labels = all_weeks_between(keys[0], keys[-1])
    else:
        all_labels = sorted(agg_bucket.keys())

    labels, user_msgs, ai_msgs, user_words, ai_words = [], [], [], [], []
    for label in all_labels:
        b = agg_bucket.get(label, {})
        labels.append(label)
        user_msgs.append(b.get("messages", {}).get("human", 0))
        ai_msgs.append(b.get("messages", {}).get("assistant", 0))
        user_words.append(b.get("human", ZERO)[0])
        ai_words.append(b.get("assistant", ZERO)[0])
    return labels, user_msgs, ai_msgs, user_words, ai_words


def share_pct(user: list[int], ai: list[int]) -> list[float]:
    result = []
    for y, a in zip(user, ai):
        total = y + a
        result.append(round(100 * y / total, 1) if total else 0.0)
    return result


# ---------- STATS TABLE ----------


def stats_table_html(title: str, bucket_dict: dict) -> str:
    """Return an HTML table of per-period stats (messages, words, share)."""
    rows = []
    for label in sorted(bucket_dict.keys()):
        b = bucket_dict[label]
        chats = b.get("conversations", 0)
        user_msg = b.get("messages", {}).get("human", 0)
        ai_msg = b.get("messages", {}).get("assistant", 0)
        user_wrd = b.get("human", ZERO)[0]
        ai_wrd = b.get("assistant", ZERO)[0]
        total_wrd = user_wrd + ai_wrd
        share = f"{100 * user_wrd / total_wrd:.1f}%" if total_wrd else "—"
        td = 'style="padding:6px 10px;text-align:right;border-bottom:1px solid #e8e8e8"'
        td0 = 'style="padding:6px 10px;text-align:left;border-bottom:1px solid #e8e8e8"'
        rows.append(
            f"<tr><td {td0}>{label}</td>"
            f"<td {td}>{chats:,}</td>"
            f"<td {td}>{user_msg:,}</td><td {td}>{ai_msg:,}</td>"
            f"<td {td}>{user_wrd:,}</td><td {td}>{ai_wrd:,}</td>"
            f"<td {td}>{share}</td></tr>"
        )
    body = "\n".join(rows)
    return f"""
<div style="max-width:900px;margin:40px auto 20px;font-family:sans-serif;font-size:13px">
  <h3 style="margin-bottom:8px">{title}</h3>
  <table style="width:100%;border-collapse:collapse">
    <thead>
      <tr style="background:#f0f0f0">
        <th style="text-align:left;padding:6px 10px">Period</th>
        <th style="text-align:right;padding:6px 10px">Chats</th>
        <th style="text-align:right;padding:6px 10px">User msgs</th>
        <th style="text-align:right;padding:6px 10px">AI msgs</th>
        <th style="text-align:right;padding:6px 10px">User words</th>
        <th style="text-align:right;padding:6px 10px">AI words</th>
        <th style="text-align:right;padding:6px 10px">User share</th>
      </tr>
    </thead>
    <tbody>
{body}
    </tbody>
  </table>
</div>"""


def write_html_with_tables(figs: list, path: Path, tables_html: str) -> None:
    """Write multiple Plotly figures to a single HTML file with table sections appended."""
    divs = [figs[0].to_html(include_plotlyjs=True, full_html=False)]
    for fig in figs[1:]:
        divs.append(fig.to_html(include_plotlyjs=False, full_html=False))
    html = (
        '<!DOCTYPE html>\n<html>\n<head><meta charset="utf-8"><title>AI Usage</title></head>\n<body>\n'
        '<h1 style="font-family:sans-serif;max-width:900px;margin:30px auto 0;padding:0 20px">AI Usage</h1>\n'
        + "".join(divs)
        + tables_html
        + "\n</body>\n</html>"
    )
    path.write_text(html, encoding="utf-8")


# ---------- BUILD FIGURES ----------


def build_figures(bucket: dict, title: str, fill_weeks: bool = False,
                  use_date_axis: bool = False) -> list:
    """Build three separate figures for a single time granularity.

    Returns [messages_fig, words_fig, share_fig].
    use_date_axis=True: convert ISO week labels (YYYY-Www) to Wednesday dates
    and apply monthly tick formatting — use for the weekly chart.
    """
    labels, user_msg, ai_msg, user_wrd, ai_wrd = bucket_series(
        bucket, fill_weeks=fill_weeks
    )
    total_msg = [u + a for u, a in zip(user_msg, ai_msg)]
    share = share_pct(user_wrd, ai_wrd)

    x = [week_to_wednesday(lbl) for lbl in labels] if use_date_axis else labels

    YOU_COLOR = "#4C9BE8"
    AI_COLOR = "#E8834C"
    SHARE_COLOR = "#2CA02C"
    TOTAL_COLOR = "#636EFA"

    xaxis_cfg = dict(tickangle=-45)
    if use_date_axis:
        xaxis_cfg.update(dtick="M1", tickformat="%b %Y")

    layout_common = dict(height=400, template="plotly_white")

    # ---- Figure 1: total messages ----
    fig1 = go.Figure()
    fig1.add_trace(go.Scatter(
        x=x, y=total_msg, name="Messages",
        mode="lines", line=dict(color=TOTAL_COLOR, width=2),
        showlegend=False,
        hovertemplate="%{x}<br>%{y:,} messages<extra></extra>",
    ))
    fig1.update_layout(
        title=dict(text=f"Messages ({title})", font=dict(size=16)),
        yaxis_title="Messages",
        **layout_common,
    )
    fig1.update_xaxes(**xaxis_cfg)

    # ---- Figure 2: words user vs AI ----
    fig2 = go.Figure()
    fig2.add_trace(go.Scatter(
        x=x, y=user_wrd, name="User",
        mode="lines", line=dict(color=YOU_COLOR, width=2),
        hovertemplate="%{x}<br>User: %{y:,} words<extra></extra>",
    ))
    fig2.add_trace(go.Scatter(
        x=x, y=ai_wrd, name="AI",
        mode="lines", line=dict(color=AI_COLOR, width=2),
        hovertemplate="%{x}<br>AI: %{y:,} words<extra></extra>",
    ))
    fig2.update_layout(
        title=dict(text=f"Words — User vs AI ({title})", font=dict(size=16)),
        yaxis_title="Words",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        **layout_common,
    )
    fig2.update_xaxes(**xaxis_cfg)

    # ---- Figure 3: user share ----
    fig3 = go.Figure()
    fig3.add_trace(go.Scatter(
        x=x, y=share, name="User share",
        mode="lines", line=dict(color=SHARE_COLOR, width=2),
        showlegend=False,
        hovertemplate="%{x}<br>User share: %{y:.1f}%<extra></extra>",
    ))
    fig3.update_layout(
        title=dict(text=f"User share of words ({title})", font=dict(size=16)),
        yaxis_title="% of total words",
        **layout_common,
    )
    fig3.update_xaxes(**xaxis_cfg)

    return [fig1, fig2, fig3]


# ---------- MAIN ----------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Plot AI usage statistics as interactive Plotly charts.")
    parser.add_argument("files", nargs="+", metavar="FILE", help="JSON export file(s)")
    parser.add_argument("--output-dir", default=".", metavar="DIR", help="Directory for output HTML files")
    parser.add_argument("--timezone", default=None, metavar="TIMEZONE", help="Timezone for timestamps (e.g. 'America/New_York'). Defaults to system timezone.")
    parser.add_argument("--start-date", default=None, metavar="YYYY-MM-DD", help="Ignore messages before this date")
    parser.add_argument("--end-date", default=None, metavar="YYYY-MM-DD", help="Ignore messages after this date")
    a = parser.parse_args()

    tz = resolve_timezone(a.timezone)

    output_dir = Path(a.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    all_records = []
    source_labels = []

    for arg in a.files:
        path = Path(arg)
        records, fmt, _ = detect_and_parse(path, tz)
        all_records.extend(records)
        source_labels.append(f"{path.name} ({fmt})")

    if a.start_date:
        all_records = [r for r in all_records if r["date"] >= a.start_date]
        print(f"Filtered to messages on or after {a.start_date} ({len(all_records)} records)")
    if a.end_date:
        all_records = [r for r in all_records if r["date"] <= a.end_date]
        print(f"Filtered to messages on or before {a.end_date} ({len(all_records)} records)")

    agg = aggregate(all_records)

    if agg["by_day"]:
        data_start = min(agg["by_day"].keys())
        data_end = max(agg["by_day"].keys())
    else:
        data_start = data_end = "—"
    overall_table = stats_table_html(
        f"Overall — {data_start} to {data_end}",
        {"All": agg["overall"]},
    )
    sources_html = (
        '<div style="max-width:900px;margin:0 auto 20px;font-family:sans-serif;font-size:13px">'
        '<p style="margin:4px 0 4px"><strong>Input files:</strong></p>'
        '<ul style="margin:0;padding-left:20px">'
        + "".join(f"<li>{s}</li>" for s in source_labels)
        + "</ul></div>"
    )

    monthly_path = output_dir / "usage_monthly.html"
    weekly_path = output_dir / "usage_weekly.html"
    daily_path = output_dir / "usage_daily.html"

    monthly_tables = (
        overall_table
        + sources_html
        + stats_table_html("By Year", agg["by_year"])
        + stats_table_html("By Month", agg["by_month"])
    )
    write_html_with_tables(
        build_figures(agg["by_month"], "Monthly"),
        monthly_path,
        monthly_tables,
    )
    print(f"Monthly report: {monthly_path}")

    weekly_tables = (
        overall_table
        + sources_html
        + stats_table_html("By Year", agg["by_year"])
        + stats_table_html("By Week", agg["by_week"])
    )
    write_html_with_tables(
        build_figures(agg["by_week"], "Weekly", fill_weeks=True, use_date_axis=True),
        weekly_path,
        weekly_tables,
    )
    print(f"Weekly report:  {weekly_path}")

    daily_tables = (
        overall_table
        + sources_html
        + stats_table_html("By Year", agg["by_year"])
        + stats_table_html("By Day", agg["by_day"])
    )
    write_html_with_tables(
        build_figures(agg["by_day"], "Daily"),
        daily_path,
        daily_tables,
    )
    print(f"Daily report:   {daily_path}")
