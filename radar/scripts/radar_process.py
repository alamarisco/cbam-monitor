#!/usr/bin/env python3
"""
RADAR mode processor — 國際新聞蒐集 daily triage (OFFLINE only).

All web fetching is done by Claude's sanctioned fetch tool (web_fetch) BEFORE this
script runs; results are passed in as local files. Nothing here touches the network.

Inputs:
  --articles   latest.json fetched from cbam-monitor (raw GitHub)            [required]
  --portals    portal_items.json — NEW EU/UK official-portal items that Claude
               assembled by diffing the portal pages vs portal_seen.json     [optional]
  --seen       seen_urls.json (dedup ledger from Drive _state)               [required]
  --queue      _queue_<week>.md (this week's picks, also deduped against)     [optional]
  --outdir     output directory                                              [required]
  --date       run date YYYY-MM-DD (default: today, Taipei)

Outputs (in --outdir):
  candidates.json          — ranked Stream A + listed Stream B (machine-readable)
  daily_digest_<date>.md   — Stream A (CBAM core), grouped by priority tier
  vcm_reference_<date>.md   — Stream B (VCM / broader), listed only
  triage_<date>.html       — interactive triage page (checkboxes + send-to-Claude)
"""
from __future__ import annotations
import argparse, json, os, re, html, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, "..", "templates", "triage_template.html")

# ── Stream / priority classification ─────────────────────────────────────────
STREAM_B_MARKERS = [
    "voluntary carbon", "vcm", "article 6", "第六條", "corsia", "aviation", "航空",
    "carbon removal", "cdr", "碳移除", "nature-based", "自然碳匯", "森林",
    "japan carbon", "日本碳", "korea carbon", "韓國碳", "南韓",
]
HIGH_MARKERS = [
    "eu cbam", "歐盟cbam", "uk carbon", "英國碳", "uk cbam", "英國cbam",
    "taiwan carbon", "台灣碳", "cement, steel", "水泥鋼鐵", "hard-to-abate",
    "industry & trade", "產業與貿易",
]
HIGH_KEYWORDS = [
    "cbam", "carbon border", "碳邊境", "碳關稅", "碳洩漏", "carbon leakage",
    "免費配額", "free allocation", "default value", "預設值",
    "塑膠版cbam", "downstream", "下游",
]
PORTAL_SOURCES = {"EU CBAM Portal", "UK CBAM Portal", "DG TAXUD CBAM"}
SOURCE_RANK = {
    "EU CBAM Portal": 100, "UK CBAM Portal": 100, "DG TAXUD CBAM": 100,
    "GMK Center": 60, "S&P Global": 60, "Carbon Pulse": 58, "Euractiv": 56,
    "Clear Blue Markets": 50, "Carbon Brief": 50, "Politico Europe": 48,
    "中央社 CNA": 46, "經濟日報 Economic Daily": 46, "聯合新聞網 UDN": 44,
    "環境資訊中心 e-info": 42,
    "Financial Times": 30, "Nikkei Asia": 30, "Bloomberg Green": 30,
}
TIER_LABEL = {"TOP": "🔴 TOP — 官方門戶更新", "HIGH": "🟠 HIGH", "MED": "🟡 MED"}
TIER_ORDER = {"TOP": 0, "HIGH": 1, "MED": 2}
TIER_COLOR = {"TOP": "#c62828", "HIGH": "#e8870c", "MED": "#b59a00"}

# ── Relevance tuning (added after live dry-run 2026-06-18) ───────────────────
# A bare "cbam" token alone is a WEAK signal → MED. STRONG signals → HIGH.
CBAM_TOKENS = ["cbam", "carbon border", "碳邊境", "碳關稅"]
STRONG_SIGNALS = [
    "carbon border adjustment", "carbon border mechanism", "carbon border tax",
    "碳邊境", "碳關稅", "cbam certificate", "cbam declarant", "cbam registry",
    "cbam scope", "cbam exemption", "cbam equivalence", "cbam importer",
    "免費配額", "free allocation", "default value", "預設值", "cbam benchmark",
    "carbon leakage", "碳洩漏", "塑膠版cbam", "downstream", "下游",
    "uk cbam", "英國cbam", "uk carbon border", "碳費", "電力排碳係數",
    "green steel", "low-carbon steel", "low-carbon cement", "steel decarbon",
    "cement decarbon", "safeguard", "保障措施", "關稅配額",
]
TAIWAN_BUCKET = ["taiwan carbon", "台灣碳"]
EVERGREEN_PAT = re.compile(
    r"^(what is|what's)\b|: your guide|\bexplained\b|your guide"
    r"|大哉問|懶人包|一次看|圖解|教戰守則|一文看懂|是什麼",
    re.I
)
DEFAULT_MAXAGE_DAYS = 4


def has_cbam(text):
    return any(t in text for t in CBAM_TOKENS)


def strong_signal(text):
    return any(s in text for s in STRONG_SIGNALS)


def is_evergreen(title, summary):
    return bool(EVERGREEN_PAT.search(title or "")) or "your guide" in (summary or "").lower()


def norm_title(t):
    t = (t or "").lower()
    t = re.sub(r"[^\w一-鿿]+", " ", t)
    return " ".join(t.split())


def dup_key(t):
    # same first 6 significant words ≈ same story across outlets (coarse on purpose;
    # Claude does the semantic same-story pass at review time)
    words = norm_title(t).split()
    return " ".join(words[:6]) if words else norm_title(t)


def bucket_text(a):
    return (a.get("topic", "") + " " + " ".join(a.get("matched_keywords", []))).lower()


def classify_stream(a):
    bt = bucket_text(a)
    blob = (a.get("title", "") + " " + a.get("summary", "")).lower() + " " + bt
    if has_cbam(blob) or any(k in blob for k in HIGH_KEYWORDS):
        return "A"
    # Taiwan-bucket items with no CBAM signal → reference, not triaged
    if any(m in bt for m in TAIWAN_BUCKET):
        return "B"
    if any(m in bt for m in STREAM_B_MARKERS):
        return "B"
    # catch-all "Other" bucket with no CBAM signal → reference, not triaged
    if "其他" in bt or "other 其他" in bt:
        return "B"
    return "A"


def priority(a):
    if a.get("source") in PORTAL_SOURCES or a.get("portal"):
        return "TOP"
    blob = (a.get("title", "") + " " + a.get("summary", "")).lower() + " " + bucket_text(a)
    # HIGH only on a STRONG signal; a lone "cbam" mention stays MED
    if strong_signal(blob):
        return "HIGH"
    return "MED"


def load_seen(path):
    if not path or not os.path.exists(path):
        return set()
    return set(json.load(open(path, encoding="utf-8")).get("urls", []))


def load_portal_seen(path):
    if not path or not os.path.exists(path):
        return set()
    try:
        return set(json.load(open(path, encoding="utf-8")).get("urls", []))
    except Exception:
        return set()


def save_portal_seen(path, seen_set):
    data = {"updated": datetime.date.today().isoformat(), "urls": sorted(seen_set)}
    json.dump(data, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


def load_queue_urls(path):
    if not path or not os.path.exists(path):
        return set()
    return set(re.findall(r"https?://\S+", open(path, encoding="utf-8").read()))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--articles", required=True)
    ap.add_argument("--portals", default="")
    ap.add_argument("--seen", required=True)
    ap.add_argument("--portal-seen", default="state/portal_seen.json",
                    dest="portal_seen",
                    help="portal dedup ledger — portal URLs seen here are suppressed")
    ap.add_argument("--queue", default="")
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--date", default=None)
    ap.add_argument("--maxage", type=int, default=DEFAULT_MAXAGE_DAYS,
                    help="drop items older than this many days before --date")
    a = ap.parse_args()

    run_date = a.date or datetime.datetime.now(
        datetime.timezone(datetime.timedelta(hours=8))).strftime("%Y-%m-%d")
    cutoff = (datetime.date.fromisoformat(run_date) -
              datetime.timedelta(days=a.maxage)).isoformat()
    os.makedirs(a.outdir, exist_ok=True)

    arts = json.load(open(a.articles, encoding="utf-8"))
    if a.portals and os.path.exists(a.portals):
        portal_items = json.load(open(a.portals, encoding="utf-8"))
        for p in portal_items:
            p["portal"] = True
        arts = portal_items + arts

    seen = load_seen(a.seen) | load_queue_urls(a.queue)
    portal_seen = load_portal_seen(a.portal_seen)

    kept = {}
    dropped_dupe = dropped_old = dropped_evergreen = dropped_portal_dupe = 0
    for art in arts:
        url = (art.get("link") or art.get("url") or "").strip()
        title = art.get("title", "")
        if not url or not title or url in seen:
            continue
        src = art.get("source", "")
        pub10 = (art.get("published", "") or "")[:10]
        summ = art.get("summary", "")
        # 1) drop the evergreen EU portal landing page (keep only dated /news/ items)
        if src == "DG TAXUD CBAM" and "/news/" not in url:
            dropped_evergreen += 1
            continue
        # 2) portal dedup — suppress items already shown in a prior run
        if src in PORTAL_SOURCES and url in portal_seen:
            dropped_portal_dupe += 1
            continue
        # 3) drop stale items — portal sources exempt (official docs don't expire)
        if pub10 and pub10 < cutoff and src not in PORTAL_SOURCES:
            dropped_old += 1
            continue
        # 3b) no date on a non-portal scraped item → treat as stale
        if not pub10 and src not in PORTAL_SOURCES:
            dropped_old += 1
            continue
        # 4) drop evergreen "what is X / your guide" explainer pages
        if is_evergreen(title, summ):
            dropped_evergreen += 1
            continue
        cand = {
            "title": title, "summary": art.get("summary", ""), "url": url,
            "source": art.get("source", ""), "published": (art.get("published", "") or "")[:10],
            "topic": art.get("topic", ""), "matched_keywords": art.get("matched_keywords", []),
            "portal": bool(art.get("portal")),
        }
        k = dup_key(title)
        if k in kept:
            dropped_dupe += 1
            if SOURCE_RANK.get(cand["source"], 40) > SOURCE_RANK.get(kept[k]["source"], 40):
                kept[k] = cand
        else:
            kept[k] = cand

    items = list(kept.values())
    for it in items:
        it["stream"] = classify_stream(it)
        it["tier"] = priority(it) if it["stream"] == "A" else "REF"

    stream_a = [i for i in items if i["stream"] == "A"]
    stream_b = [i for i in items if i["stream"] == "B"]
    stream_a.sort(key=lambda i: i["published"], reverse=True)
    stream_a.sort(key=lambda i: TIER_ORDER.get(i["tier"], 9))
    stream_b.sort(key=lambda i: i["published"], reverse=True)

    # Persist portal URLs seen this run so they don't surface as TOP every day
    new_portal_urls = {it["url"] for it in items if it.get("source") in PORTAL_SOURCES}
    if new_portal_urls:
        save_portal_seen(a.portal_seen, portal_seen | new_portal_urls)

    json.dump(
        {"date": run_date, "stream_a": stream_a, "stream_b": stream_b,
         "stats": {"a": len(stream_a), "b": len(stream_b), "dupes_collapsed": dropped_dupe,
                   "dropped_stale": dropped_old, "dropped_evergreen": dropped_evergreen,
                   "dropped_portal_repeat": dropped_portal_dupe}},
        open(os.path.join(a.outdir, "candidates.json"), "w", encoding="utf-8"),
        ensure_ascii=False, indent=2)

    write_digest(os.path.join(a.outdir, f"daily_digest_{run_date}.md"), run_date, stream_a, dropped_dupe)
    write_vcm(os.path.join(a.outdir, f"vcm_reference_{run_date}.md"), run_date, stream_b)
    write_triage(os.path.join(a.outdir, f"triage_{run_date}.html"), run_date, stream_a, stream_b, dropped_dupe)

    nt = sum(1 for i in stream_a if i["tier"] == "TOP")
    nh = sum(1 for i in stream_a if i["tier"] == "HIGH")
    nm = sum(1 for i in stream_a if i["tier"] == "MED")
    print(f"[RADAR] {run_date}: Stream A {len(stream_a)} (TOP {nt}, HIGH {nh}, MED {nm}) · "
          f"Stream B {len(stream_b)} · {dropped_dupe} dupes · "
          f"{dropped_old} stale · {dropped_evergreen} evergreen · "
          f"{dropped_portal_dupe} portal repeats suppressed")
    print(f"[OUT] {a.outdir}")


def write_digest(path, run_date, stream_a, dupes):
    md = [f"# 國際新聞蒐集 — 每日雷達 (Stream A · CBAM core) — {run_date}", ""]
    md.append(f"_{len(stream_a)} candidates after dedup · {dupes} duplicates collapsed_\n")
    for tier in ("TOP", "HIGH", "MED"):
        group = [i for i in stream_a if i["tier"] == tier]
        if not group:
            continue
        md.append(f"## {TIER_LABEL[tier]} ({len(group)})\n")
        for i in group:
            md.append(f"- **{i['title']}**")
            md.append(f"  {i['source']} · {i['published']} · _{i['topic']}_")
            if i["summary"]:
                md.append(f"  {i['summary'][:200]}")
            md.append(f"  {i['url']}\n")
    open(path, "w", encoding="utf-8").write("\n".join(md))


def write_vcm(path, run_date, stream_b):
    md = [f"# VCM / 廣義碳市場參考清單 (Stream B · 研究用, 不進 CBAM 週報) — {run_date}", ""]
    md.append(f"_{len(stream_b)} items — collected for research; seed for a future VCM newsletter._\n")
    for i in stream_b:
        md.append(f"- **{i['title']}** — {i['source']} · {i['published']} · _{i['topic']}_")
        md.append(f"  {i['url']}")
    open(path, "w", encoding="utf-8").write("\n".join(md))


def write_triage(path, run_date, stream_a, stream_b, dupes):
    esc = lambda s: html.escape(s or "")
    rows = []
    for i in stream_a:
        pre = "checked" if i["tier"] in ("TOP", "HIGH") else ""
        rows.append(
            '<label class="row" data-tier="{t}">'
            '<input type="checkbox" {pre} data-url="{u}" data-title="{ti}">'
            '<span class="badge" style="background:{col}">{t}</span>'
            '<span class="meta">{src} · {pub} · {top}</span>'
            '<a class="title" href="{u}" target="_blank" rel="noopener">{ti}</a>'
            '<span class="sum">{sum}</span></label>'.format(
                t=i["tier"], pre=pre, col=TIER_COLOR[i["tier"]], u=esc(i["url"]),
                ti=esc(i["title"]), src=esc(i["source"]), pub=esc(i["published"]),
                top=esc(i["topic"]), sum=esc(i["summary"][:180])))
    brows = []
    for i in stream_b:
        brows.append(
            '<div class="brow"><span class="meta">{src} · {pub} · {top}</span>'
            '<a href="{u}" target="_blank" rel="noopener">{ti}</a></div>'.format(
                src=esc(i["source"]), pub=esc(i["published"]), top=esc(i["topic"]),
                u=esc(i["url"]), ti=esc(i["title"])))
    tpl = open(TEMPLATE, encoding="utf-8").read()
    out = (tpl.replace("__DATE__", run_date)
              .replace("__NA__", str(len(stream_a)))
              .replace("__DUP__", str(dupes))
              .replace("__NB__", str(len(stream_b)))
              .replace("__ROWS__", "".join(rows))
              .replace("__BROWS__", "".join(brows) if brows else "<p class=sub>None today.</p>"))
    open(path, "w", encoding="utf-8").write(out)


if __name__ == "__main__":
    main()
