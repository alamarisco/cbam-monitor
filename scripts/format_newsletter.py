#!/usr/bin/env python3
"""
CBAM Global Monitor — Newsletter Formatter
==========================================
Reads a JSON array of articles (output of fetch_feeds.py --format json)
and formats it as a two-tier HTML newsletter or Markdown document.

Two-tier HTML structure:
  1. Key Developments — one lead item per topic (up to 6), scannable digest
  2. Full briefing — jurisdiction-organized sections with summaries

Usage:
  python format_newsletter.py --input /tmp/articles.json --output /tmp/cbam.html
  python format_newsletter.py --input /tmp/articles.json --output /tmp/cbam.md --format markdown
"""

import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone


TOPIC_ORDER = [
    "EU CBAM — Policy & Implementation 歐盟CBAM政策",
    "EU ETS 歐盟碳交易",
    "UK Carbon Market 英國碳市場",
    "Taiwan Carbon Market 台灣碳市場",
    "Japan Carbon Market 日本碳市場",
    "Korea Carbon Market 韓國碳市場",
    "Voluntary Carbon Market (VCM) 自願性碳市場",
    "Article 6 & Paris Agreement 第六條",
    "CORSIA & Aviation 航空碳抵換",
    "Carbon Removal & CDR 碳移除",
    "Nature-based Solutions 自然碳匯",
    "Cement, Steel & Hard-to-Abate Industry 水泥鋼鐵與高碳產業",
    "Industry & Trade Response 產業與貿易回應",
    "Analysis & Research 分析與研究",
    "Other 其他",
]

GREEN = "#2e7d32"
GREEN_LIGHT = "#e8f5e9"
GREEN_DARK = "#1b5e20"


def format_pub_date(iso_str: str) -> str:
    """Convert ISO timestamp to compact Taipei-time string e.g. 'May 19 · 09:41'."""
    try:
        dt = datetime.fromisoformat(iso_str)
        taipei_tz = timezone(timedelta(hours=8))
        dt_taipei = dt.astimezone(taipei_tz)
        return dt_taipei.strftime("%b %-d · %H:%M")
    except Exception:
        return iso_str[:10] if iso_str else ""


def first_sentence(text: str, max_chars: int = 160) -> str:
    """Extract the first sentence, capped at max_chars."""
    if not text:
        return ""
    sentences = re.split(r"(?<=[.!?])\s", text.strip())
    s = sentences[0] if sentences else text
    return s[:max_chars] + ("…" if len(s) > max_chars else "")


def kw_pill(kw: str, bg: str = GREEN_LIGHT, fg: str = GREEN) -> str:
    return (
        f'<span style="background:{bg};color:{fg};padding:2px 6px;'
        f'border-radius:3px;font-size:11px;margin-right:4px;">{kw}</span>'
    )


def format_html(articles: list, run_time: str) -> str:
    by_topic: dict[str, list] = defaultdict(list)
    for a in articles:
        by_topic[a.get("topic", "Other 其他")].append(a)

    # ── Full topic sections ──────────────────────────────────────────────────
    sections = ""
    for topic in TOPIC_ORDER:
        items = by_topic.get(topic, [])
        if not items:
            continue

        rows = ""
        for a in items:
            pub = format_pub_date(a.get("published", ""))

            if a.get("type") == "free" and a.get("summary"):
                body = (
                    f'<p style="color:#444;font-size:14px;margin:5px 0 6px 0;">'
                    f'{a["summary"]}</p>'
                )
            else:
                body = (
                    '<p style="color:#aaa;font-size:13px;font-style:italic;'
                    'margin:5px 0 6px 0;">Full text behind paywall.</p>'
                )

            rows += f"""
            <div style="padding:11px 0 7px 0;">
              <a href="{a.get('link','#')}" style="color:#1a0dab;font-size:15px;
                 text-decoration:none;font-weight:600;">{a.get('title','')}</a><br/>
              <span style="color:#1565c0;font-size:12px;font-weight:600;">
                {a.get('source','')}
              </span>
              <span style="color:#888;font-size:12px;"> &middot; {pub}</span>
              {body}
            </div>
            <div style="border-bottom:1px solid #eee;"></div>"""

        sections += f"""
        <div style="margin-bottom:30px;">
          <h2 style="color:#202124;font-size:17px;border-bottom:2px solid {GREEN};
              padding-bottom:6px;margin-bottom:10px;">{topic}
            <span style="font-size:13px;color:#888;font-weight:normal;">
              ({len(items)})</span>
          </h2>
          {rows}
        </div>"""

    total = len(articles)
    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>CBAM Global Monitor</title>
</head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,
  Helvetica,Arial,sans-serif;max-width:680px;margin:0 auto;padding:16px 20px;
  color:#202124;background:#fff;">

  <div style="text-align:center;padding:18px 0;border-bottom:3px solid {GREEN};">
    <h1 style="margin:0;font-size:22px;color:#202124;line-height:1.3;">
      CBAM Global Monitor<br/>
      <span style="font-size:15px;color:#555;font-weight:400;">
        碳邊境調整機制週報
      </span>
    </h1>
    <p style="margin:8px 0 0 0;color:#666;font-size:13px;">
      {run_time} &middot; {total} articles
    </p>
  </div>

  {sections}

  <div style="text-align:center;padding:18px 0;border-top:1px solid #ddd;
       color:#aaa;font-size:11px;line-height:1.7;">
    Carbon Markets Global Monitor &middot; Weekly Edition<br/>
    Sources: Euractiv · Carbon Brief · Carbon Pulse · Carbon Market Watch ·
    Climate Home News · Politico Europe · E3G · Sandbag · Ember Energy ·
    Clear Blue Markets · Sylvera · BeZero Carbon · 今週刊 ESG · CNA · UDN ·
    Economic Daily · 環境資訊中心 · 天下雜誌 · FT · Nikkei Asia · Bloomberg Green
  </div>

</body>
</html>"""


def format_markdown(articles: list, run_time: str) -> str:
    by_topic: dict[str, list] = defaultdict(list)
    for a in articles:
        by_topic[a.get("topic", "Other 其他")].append(a)

    lines = [
        "# CBAM Global Monitor 碳邊境調整機制週報",
        f"**Generated**: {run_time}  ",
        f"**Articles**: {len(articles)}",
        "",
        "## Key Developments This Week",
        "",
    ]

    key_items = []
    for topic in TOPIC_ORDER:
        items = by_topic.get(topic, [])
        if items:
            key_items.append((topic, items[0]))
        if len(key_items) >= 6:
            break

    for topic, a in key_items:
        short = topic.split("—")[0].strip()
        en_only = re.split(r"[一-鿿]", short)[0].strip().rstrip("& ")
        tag = en_only if en_only else short[:18]
        excerpt = first_sentence(a.get("summary", "")) if a.get("type") == "free" else ""
        sep = " — " if excerpt else ""
        lines.append(f"- **[{tag}]** [{a.get('title','')}]({a.get('link','')}) {sep}{excerpt}")

    lines.extend(["", "---", ""])

    for topic in TOPIC_ORDER:
        items = by_topic.get(topic, [])
        if not items:
            continue
        lines.append(f"## {topic} ({len(items)})")
        lines.append("")
        for a in items:
            kw = ", ".join(a.get("matched_keywords", [])[:5])
            pub = format_pub_date(a.get("published", ""))
            lines.append(f"### [{a.get('title','')}]({a.get('link','')})")
            lines.append(f"**{a.get('source','')}** | {pub} | {kw}")
            if a.get("type") == "free" and a.get("summary"):
                lines.append(f"\n{a['summary']}")
            lines.extend(["", "---", ""])

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="CBAM Global Monitor — Newsletter Formatter"
    )
    parser.add_argument("--input", required=True, help="Input JSON file from fetch_feeds.py")
    parser.add_argument("--output", required=True, help="Output file path")
    parser.add_argument(
        "--format", default="html", choices=["html", "markdown"],
        help="Output format (default: html)"
    )
    args = parser.parse_args()

    with open(args.input, "r", encoding="utf-8") as f:
        articles = json.load(f)

    taipei_tz = timezone(timedelta(hours=8))
    run_time = datetime.now(tz=taipei_tz).strftime("%Y-%m-%d %H:%M (Taipei)")

    if args.format == "markdown":
        output = format_markdown(articles, run_time)
    else:
        output = format_html(articles, run_time)

    with open(args.output, "w", encoding="utf-8") as f:
        f.write(output)

    print(f"[OUT] {len(articles)} articles → {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
