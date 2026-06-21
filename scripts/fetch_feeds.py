#!/usr/bin/env python3
"""
CBAM Global Monitor — News Aggregator
======================================
Fetches news on carbon border adjustment mechanisms (CBAM) from free and paid
RSS feeds across EU, UK, Taiwan, and global trade sources. Keyword-filters
for CBAM relevance, classifies by jurisdiction/topic, and outputs HTML, JSON,
or Markdown.

Data sources:
  Free (RSS)     — Euractiv, Carbon Brief, Carbon Pulse, Carbon Market Watch,
                   Climate Home News, E3G, Sandbag (CBAM category), Clear Blue Markets,
                   Politico Europe, EUROMETAL, SteelOrbis, GMK Center, Carbon Credits,
                   EU Council, Business Standard India, NDTV Profit India,
                   中央社 CNA, 聯合新聞網 UDN, 經濟日報 Economic Daily (incl. 商情/ESG), 環境資訊中心 e-info
  Free (scraped) — Sylvera (sylvera.com/blog), BeZero Carbon (bezerocarbon.com/insights),
                   今週刊 ESG (esg.businesstoday.com.tw), Ember Energy (ember-energy.org),
                   DG TAXUD CBAM (ec.europa.eu), 經貿透視 Trademag
  Paid (scraped) — 天下雜誌 CommonWealth (cw.com.tw — 永續發展 section; preview only)
                   All confirmed SSR; link-pattern scraper, no JS needed.
  Paid (RSS)     — Financial Times, Nikkei Asia, Bloomberg Green, S&P Global Commodity Insights
  Dead (removed) — Reuters (all RSS feeds shut down May 2026)
  Removed feeds  — Parliament Magazine, PIK Potsdam (no native RSS),
                   CNBC TV18 India (geo-blocked; replaced by Business Standard),
                   Reccessary, Cnyes, CSRone (no valid RSS),
                   CTEE, CNA Net Zero (403/JS-rendered)

Clear Blue Markets notes (confirmed via Chrome, May 2026):
  - Correct domain: clearbluemarkets.com (NOT clearblue.markets)
  - RSS feed: /knowledge-base/rss.xml — full articles, ISO dates, <category>CBAM</category> tags
  - /news/rss.xml also works — company news/press releases (lower priority)

Feed URL verification status (run check_feeds.py from Codespace to confirm):
  ✅ Confirmed (same as working semiconductor newsletter):
       CNA FeedBurner, Economic Daily UDN, FT (world/markets/companies/asia-pacific), Nikkei
  ⚠️  Unverified (CBAM-specific, sandbox cannot reach outbound):
       Euractiv, Carbon Brief, Carbon Pulse, E3G, Sandbag, Ember Climate
  🔍 Scraped (no RSS — confirmed SSR via Chrome inspection):
       Sylvera (sylvera.com/blog), BeZero Carbon (bezerocarbon.com/insights)
  🔧 Fixed vs. original draft:
       Reuters /environment and /businessnews (corrected from /environmentNews, /businessNews)
       FT /world/europe added (unverified — remove if it 404s)

Usage:
  python fetch_feeds.py --hours 168 --format html --output /tmp/cbam.html
  python fetch_feeds.py --hours 168 --format json --output /tmp/articles.json
  python fetch_feeds.py --hours 168 --format markdown --output /tmp/cbam.md
  python fetch_feeds.py --hours 168 --debug
"""

from __future__ import annotations

import argparse
import html as html_module
import json
import re
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin

# ── Optional imports ──────────────────────────────────────────────────────────

try:
    import feedparser
    HAS_FEEDPARSER = True
except ImportError:
    HAS_FEEDPARSER = False
    print("[WARN] feedparser not installed — RSS sources skipped.", file=sys.stderr)
    print("       pip install feedparser", file=sys.stderr)

try:
    import requests
    from bs4 import BeautifulSoup
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

# ── HTTP config ───────────────────────────────────────────────────────────────

HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/121.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9,zh-TW;q=0.8,zh;q=0.7",
}

REQUEST_TIMEOUT = 15
MAX_SUMMARY_LEN = 400

# ── RSS Feed Configuration ────────────────────────────────────────────────────

RSS_FEEDS: dict[str, dict] = {

    # ── FREE SOURCES (headline + summary + link) ──────────────────────────

    "Euractiv": {
        "type": "free",
        "method": "rss",
        # Section feeds blocked by Cloudflare (return HTML) — main feed only (confirmed May 2026)
        "feeds": [
            "https://www.euractiv.com/feed/",
        ],
    },

    "Carbon Brief": {
        "type": "free",
        "method": "rss",
        # FeedBurner URL hijacked (May 2026) — direct feed is authoritative
        "feeds": [
            "https://www.carbonbrief.org/feed/",
        ],
    },

    "Carbon Pulse": {
        "type": "free",
        "method": "rss",
        "feeds": [
            # Topic-specific category feeds (confirmed May 2026)
            "https://carbon-pulse.com/category/international/cbam-tariffs/feed/",
            "https://carbon-pulse.com/category/emea/emea-compliance-markets-taxes/feed/",
            "https://carbon-pulse.com/category/international/paris-article-6/feed/",
            "https://carbon-pulse.com/category/international/aviation/feed/",
            "https://carbon-pulse.com/category/voluntary/vcm-developments/feed/",
            "https://carbon-pulse.com/category/voluntary/vcm-governance/feed/",
            "https://carbon-pulse.com/category/asia-pacific/apac-compliance-markets-taxes/feed/",
            "https://carbon-pulse.com/category/asia-pacific/asia/feed/",
            "https://carbon-pulse.com/category/nature-based-carbon/feed/",
            "https://carbon-pulse.com/category/co2-management/engineered-removals/feed/",
            "https://carbon-pulse.com/feed/",  # general feed as fallback
        ],
    },

    "Carbon Market Watch": {
        "type": "free",
        "method": "rss",
        "feeds": [
            "https://carbonmarketwatch.org/feed/",
        ],
    },

    "Climate Home News": {
        "type": "free",
        "method": "rss",
        "feeds": [
            "https://www.climatechangenews.com/feed/",
        ],
    },

    "Politico Europe": {
        "type": "free",
        "method": "rss",
        # Energy section feed confirmed working (31 entries, May 2026)
        # Main feed also works (10 entries) but energy section is more targeted
        "feeds": [
            "https://www.politico.eu/section/energy/feed/",
            "https://www.politico.eu/feed/",
        ],
    },

    "E3G": {
        "type": "free",
        "method": "rss",
        "feeds": [
            "https://www.e3g.org/feed/",
        ],
    },

    "Sandbag": {
        "type": "free",
        "method": "rss",
        # sandbag.org.uk empty — EU entity at sandbag.be is active (confirmed May 2026)
        # sandbag.be/feed/ removed: returns IncompleteRead (516 KB) on GitHub Actions
        "feeds": [
            "https://sandbag.be/category/cbam/feed/",
        ],
    },

    # Ember Energy RSS (ember-energy.org/feed/) returns malformed — Cloudflare blocks feedparser.
    # Moved to LINK_PATTERN_SOURCES scraper below.

    "Clear Blue Markets": {
        "type": "free",
        "method": "rss",
        "feeds": [
            "https://www.clearbluemarkets.com/knowledge-base/rss.xml",
            "https://www.clearbluemarkets.com/news/rss.xml",
        ],
    },

    "中央社 CNA": {
        "type": "free",
        "method": "rss",
        "feeds": [
            "https://feeds.feedburner.com/rsscna/finance",      # 財經
            "https://feeds.feedburner.com/rsscna/intworld",     # 國際
            "https://feeds.feedburner.com/rsscna/mainland",     # 兩岸
            "https://feeds.feedburner.com/rsscna/technology",   # 科技
            "https://feeds.feedburner.com/rsscna/politics",     # 政治
        ],
    },

    "經濟日報 Economic Daily": {
        "type": "free",
        "method": "rss",
        "feeds": [
            "https://money.udn.com/rssfeed/news/1001/5588?ch=news",   # 國際
            "https://money.udn.com/rssfeed/news/1001/5589?ch=news",   # 兩岸
            "https://money.udn.com/rssfeed/news/1001/5591?ch=news",   # 產業
            "https://money.udn.com/rssfeed/news/1001/5597?ch=news",   # 商情
        ],
    },

    "聯合新聞網 UDN": {
        "type": "free",
        "method": "rss",
        # 要聞 feed — 298 entries, full titles + summaries confirmed working
        # Note: earlier-tested udn.com category feeds returned empty titles; 6638 is the correct feed
        "feeds": [
            "https://udn.com/news/rssfeed/6638",    # 要聞 (major news)
        ],
    },

    "環境資訊中心 e-info": {
        "type": "free",
        "method": "rss",
        # 25 entries per fetch, proper dates; summaries empty in feed (title-only keyword match)
        # Confirmed working May 2026: https://e-info.org.tw/rss/eic.xml
        "feeds": [
            "https://e-info.org.tw/rss/eic.xml",
        ],
    },

    # ── PAID SOURCES (headline + link only) ──────────────────────────────

    "Financial Times": {
        "type": "paid",
        "method": "rss",
        "feedparser_headers": {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/121.0.0.0 Safari/537.36"
            ),
            "Accept": "application/rss+xml, application/xml, text/xml;q=0.9, */*;q=0.8",
        },
        "feeds": [
            # Confirmed working (same as semiconductor newsletter):
            "https://www.ft.com/world?format=rss",
            "https://www.ft.com/markets?format=rss",
            "https://www.ft.com/companies?format=rss",
            "https://www.ft.com/world/asia-pacific?format=rss",
            # Added for EU coverage — unverified, remove if it 404s:
            "https://www.ft.com/world/europe?format=rss",
        ],
    },

    "Nikkei Asia": {
        "type": "paid",
        "method": "rss",
        "feeds": [
            "https://asia.nikkei.com/rss/feed/nar",
        ],
    },

    "Bloomberg Green": {
        "type": "paid",
        "method": "rss",
        # Paywalled — headline + link only (same treatment as FT)
        # Feed confirmed working (May 2026): ~20 entries, ~157 char summaries
        "feeds": [
            "https://feeds.bloomberg.com/green/news.rss",
        ],
    },

    # ── STEEL & METALS TRADE ─────────────────────────────────────────────

    "EUROMETAL": {
        "type": "free",
        "method": "rss",
        # European metals association news (CBAM steel/aluminium coverage)
        "feeds": [
            "https://www.eurometal.net/feed/",
        ],
    },

    "SteelOrbis": {
        "type": "free",
        "method": "rss",
        "feedparser_headers": {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "application/rss+xml, application/xml, text/xml;q=0.9, */*;q=0.8",
        },
        "feeds": [
            "https://www.steelorbis.com/steel-news/rss/",
            "https://www.steelorbis.com/rss.xml",
        ],
    },

    "GMK Center": {
        "type": "free",
        "method": "rss",
        # Ukrainian steel industry analytics — strong CBAM coverage
        "feeds": [
            "https://gmk.center/en/feed/",
        ],
    },

    # ── EU POLICY ────────────────────────────────────────────────────────

    "EU Council": {
        "type": "free",
        "method": "rss",
        # Correct URL confirmed June 2026 — /en/press/press-releases/rss/ was wrong path.
        # pressreleases.ashx carries CBAM milestones (e.g. June 12 "Council moves to strengthen CBAM").
        # Optional: THMENV.xml for environment subject-matter filter (lower volume).
        "feeds": [
            "https://www.consilium.europa.eu/en/rss/pressreleases.ashx",
            "https://www.consilium.europa.eu/en/register/rss/THMENV.xml",
        ],
    },

    # The Parliament Magazine: no native RSS (custom CMS, no feed link) — removed.

    # ── CARBON MARKETS ───────────────────────────────────────────────────

    "Carbon Credits": {
        "type": "free",
        "method": "rss",
        "feeds": [
            "https://carboncredits.com/feed/",
        ],
    },

    # PIK Potsdam: both /en/news/rss and /en/news/latest-news/@@rss return malformed — removed.

    # ── INDIA ────────────────────────────────────────────────────────────

    # CNBC TV18 India: both RSS feeds geo-blocked from GitHub Actions — replaced by Business Standard.

    "Business Standard India": {
        "type": "free",
        "method": "rss",
        # Replacement for CNBC TV18 — verified valid June 2026, carries steel/tariff/carbon items.
        # Note: re-check entry dates from Actions runner; cowork saw some early-May dates in fetch.
        "feeds": [
            "https://www.business-standard.com/rss/economy-102.rss",
        ],
    },

    "NDTV Profit India": {
        "type": "free",
        "method": "rss",
        "feeds": [
            "https://feeds.feedburner.com/ndtvprofit-latest",
        ],
    },

    # ── TAIWAN (additional) ──────────────────────────────────────────────

    # 工商時報 CTEE: RSS returns 403, search page also returns 403 — removed entirely.
    # Reccessary /feed/ returns malformed — removed.
    # 鉅亨網 Cnyes API /news/category/*/rss returns malformed (non-standard format) — removed.
    # CSRone /feed/ returns malformed — removed.

    # ── PAID (COMMODITY INTELLIGENCE) ───────────────────────────────────

    "S&P Global Commodity Insights": {
        "type": "paid",
        "method": "rss",
        # Old /commodityinsights/ path redirects — updated to current /commodity-insights/ domain (June 2026)
        "feeds": [
            "https://www.spglobal.com/commodity-insights/en/rss-feed/energy",
            "https://www.spglobal.com/commodity-insights/en/rss-feed/metals",
        ],
    },

    # Reuters RSS feeds shut down — all URLs return connection error or 401 (confirmed May 2026)
}

# ── Link Pattern Sources (scraped — no RSS available) ────────────────────────
# Both sites confirmed SSR via Chrome inspection (May 2026): full article content
# is returned by static HTTP requests, no JavaScript rendering required.
# Strategy: fetch listing page → collect article hrefs by regex pattern →
# keyword-filter titles → fetch individual pages for date + summary.

MAX_DETAIL_FETCHES = 15   # max individual article pages to fetch per source per run
SCRAPE_DELAY      = 0.3   # polite inter-request delay (seconds)

LINK_PATTERN_SOURCES: dict[str, dict] = {
    "Sylvera": {
        "type": "free",
        "listing_url": "https://www.sylvera.com/blog",
        "base_url": "https://www.sylvera.com",
        # Match /blog/slug — exclude /blog-category/… and bare /blog
        "link_pattern": re.compile(r"^/blog/[a-z0-9][^/]*$"),
        # No reliable date metadata — regex picks up policy dates not publish dates
        "skip_date_filter": True,
    },
    "BeZero Carbon": {
        "type": "free",
        "base_url": "https://bezerocarbon.com",
        # Listing page is JS-rendered (only 2 static articles) — use sitemap instead
        "sitemap_url": "https://bezerocarbon.com/sitemap.xml",
        "link_pattern": re.compile(r"https://bezerocarbon\.com/insights/[a-z0-9][^?#]*$"),
    },
    "今週刊 ESG": {
        "type": "free",
        "listing_url": "https://esg.businesstoday.com.tw",
        "base_url": "https://esg.businesstoday.com.tw",
        # Post IDs are 12-digit sequences like 202406190001 — the first 8 digits look like
        # YYYYMMDD but they encode year 2024 for content still on the homepage, causing
        # false "too old" rejections. Removed date_from_url_regex; rely on page-level date.
        "link_pattern": re.compile(
            r"https://esg\.businesstoday\.com\.tw/article/category/\d+/post/\d{12}"
        ),
    },
    "天下雜誌 CommonWealth": {
        "type": "paid",
        "listing_url": "https://www.cw.com.tw/subchannel.action?idSubChannel=607",
        "base_url": "https://www.cw.com.tw",
        # Absolute URLs; date from JSON-LD datePublished on article pages
        "link_pattern": re.compile(r"https://www\.cw\.com\.tw/article/\d+$"),
    },
    # 工商時報 CTEE: RSS /rss/all.xml returns 403; search page also returns 403 — removed.
    "DG TAXUD CBAM": {
        "type": "free",
        "listing_url": "https://taxation-customs.ec.europa.eu/carbon-border-adjustment-mechanism_en",
        "base_url": "https://taxation-customs.ec.europa.eu",
        # EC CBAM info/news pages — date from article:published_time meta
        "link_pattern": re.compile(
            r"https://taxation-customs\.ec\.europa\.eu/[a-z0-9_-]+_en$"
        ),
        "skip_date_filter": True,
    },
    "經貿透視 Trademag": {
        "type": "free",
        "listing_url": "https://www.trademag.org.tw/",
        "base_url": "https://www.trademag.org.tw",
        # Article URLs: /page/newsidNNN/?id=XXXX (relative in HTML).
        # Pattern matches both relative (/page/newsidNNN) and absolute forms.
        # keep_query_string=True preserves ?id=XXXX so the fetch URL is valid.
        "link_pattern": re.compile(
            r"(?:https://www\.trademag\.org\.tw)?/page/newsid\d+"
        ),
        "keep_query_string": True,
    },
    # 中央社 Net Zero topic page is JS-rendered (0 static <a href> links) — removed.
    # CNA coverage continues via 中央社 CNA FeedBurner RSS feeds above.
    "Ember Energy": {
        "type": "free",
        "listing_url": "https://ember-energy.org/latest-insights/",
        "base_url": "https://ember-energy.org",
        # RSS feed blocked by Cloudflare — scrape listing page instead.
        # URL pattern: /latest-insights/<slug>/ (relative paths in listing HTML)
        "link_pattern": re.compile(
            r"(?:https://ember-energy\.org)?/latest-insights/[a-z0-9][^?#]*"
        ),
    },
    # UK CBAM Portal — official GOV.UK CBAM collection (all HMRC guidance, consultations,
    # publications). Named "UK CBAM Portal" so radar_process.py promotes to TOP tier.
    # Collection page is SSR; article URLs are relative gov.uk paths.
    "UK CBAM Portal": {
        "type": "free",
        "listing_url": "https://www.gov.uk/government/collections/carbon-border-adjustment-mechanism",
        "base_url": "https://www.gov.uk",
        "link_pattern": re.compile(
            r"(?:https://www\.gov\.uk)?/(?:guidance|government/(?:publications|consultations|"
            r"news|speeches|statistics|policy-papers))/[a-z0-9][a-z0-9-]*(?:/[a-z0-9-]+)*$"
        ),
        "skip_date_filter": True,
    },
}

# ── Keyword Configuration ─────────────────────────────────────────────────────

# English — matched case-insensitively against title + description + content + tags
KEYWORDS_EN = [
    # ── CBAM ─────────────────────────────────────────────────────────────
    "CBAM",
    "carbon border adjustment",
    "carbon border mechanism",
    "border carbon adjustment",
    "carbon border tax",
    "embedded emissions",
    "CBAM certificate",
    "CBAM declarant",
    "CBAM transitional",
    "CBAM definitive",
    "CBAM reporting",
    "CBAM registry",
    "CBAM scope",
    "CBAM equivalence",
    "CBAM exemption",
    "CBAM expansion",
    "CBAM compliance",
    "CBAM importer",
    "UK carbon border",
    "UK CBAM",
    "CBAM WTO",
    "carbon pricing equivalence",
    "carbon leakage",
    # Core-mechanism mechanics (2026 live debates)
    "free allocation",
    "MRV",
    "suspension clause",
    "downstream extension",
    "plastic CBAM",
    "aluminium CBAM",
    "aluminum CBAM",
    "fertiliser CBAM",
    "fertilizer CBAM",
    "urea CBAM",
    "hydrogen CBAM",

    # ── EU ETS ───────────────────────────────────────────────────────────
    "EU ETS",
    "European Emissions Trading",
    "ETS reform",
    "carbon allowance",
    "carbon permit",
    "EUA price",
    "EU carbon market",
    "emissions trading scheme",
    "cap and trade",

    # ── UK carbon market ─────────────────────────────────────────────────
    "UK ETS",
    "UK emissions trading",
    "UK carbon market",
    "UK carbon price",

    # ── Taiwan carbon market ──────────────────────────────────────────────
    "Taiwan carbon",
    "Taiwan ETS",
    "Taiwan carbon fee",
    "TCX carbon",
    "Taiwan carbon market",

    # ── Japan carbon market ───────────────────────────────────────────────
    "Japan ETS",
    "Japan carbon market",
    "Japan carbon pricing",
    "GX-ETS",
    "GX League",
    "Japan emissions trading",

    # ── Korea carbon market ───────────────────────────────────────────────
    "Korea ETS",
    "K-ETS",
    "South Korea carbon",
    "Korea carbon market",
    "Korea emissions trading",

    # ── Voluntary Carbon Market ───────────────────────────────────────────
    "voluntary carbon market",
    "carbon credit",
    "carbon offset",
    "carbon registry",
    "ICVCM",
    "CCP label",
    "Core Carbon Principles",
    "Verra",
    "Gold Standard",
    "carbon standard",
    "VCM",

    # ── Article 6 & Paris Agreement ───────────────────────────────────────
    "Article 6",
    "Paris Agreement carbon",
    "ITMOs",
    "corresponding adjustment",
    "Article 6.2",
    "Article 6.4",
    "carbon crediting mechanism",

    # ── CORSIA & aviation ─────────────────────────────────────────────────
    "CORSIA",
    "aviation carbon",
    "aviation offset",
    "sustainable aviation fuel",
    "SAF carbon",
    "ICAO carbon",

    # ── Carbon removal & CDR ──────────────────────────────────────────────
    "carbon removal",
    "CDR",
    "direct air capture",
    "DAC carbon",
    "biochar carbon",
    "enhanced weathering",
    "carbon dioxide removal",

    # ── Nature-based solutions ────────────────────────────────────────────
    "nature-based carbon",
    "forest carbon",
    "REDD+",
    "blue carbon",
    "soil carbon credit",
    "nature-based solution",

    # ── Cement, steel & hard-to-abate ────────────────────────────────────
    "green steel",
    "steel decarbonisation",
    "steel decarbonization",
    "cement decarbonisation",
    "cement decarbonization",
    "hard-to-abate",
    "blast furnace",
    "electric arc furnace",
    "direct reduced iron",
    "low-carbon steel",
    "low-carbon cement",
    "EUROFER",
    "steel tariff",
    "aluminium tariff",
    "aluminum tariff",
    "HBI carbon",

    # ── India & emerging markets ──────────────────────────────────────────
    "India CBAM",
    "India carbon border",
    "India carbon tax",
    "India carbon market",
    "India ETS",
    "India carbon credit",
    "BIS carbon",
    "CBAM India",
    "India steel CBAM",
    "India aluminium CBAM",
    "Turkey ETS",
    "Australia carbon leakage",

    # ── Company watch (CBAM-exposed producers) ────────────────────────────
    "Norsk Hydro",
    "TCC cement",
]

# Chinese — matched as-is (no lowercasing) against same combined text
KEYWORDS_ZH = [
    # CBAM
    "碳邊境調整機制",
    "碳邊境調節機制",
    "碳邊境調整",
    "碳關稅",
    "碳邊境稅",
    "歐盟碳邊境",
    "碳洩漏",
    "英國碳邊境",
    "碳邊境 出口",
    "碳邊境 鋼鐵",
    "碳邊境 鋁業",
    "CBAM",
    "CBAM憑證",
    "免費配額",
    "暫停條款",
    "下游擴展",
    "塑膠版CBAM",
    "塑膠碳關稅",
    "鋁業碳關稅",
    "鋁CBAM",
    "化肥碳費",
    "尿素碳稅",

    # EU/UK ETS
    "歐盟碳排放交易",
    "碳排放配額",
    "英國碳市場",
    "碳交易體系",

    # Taiwan
    "台灣碳費",
    "台灣碳市場",
    "碳費",
    "台灣碳權交易所",
    "碳排放交易所",
    "碳盤查",
    "碳中和",
    "淨零碳排",
    "排碳",
    "環境部",
    "彭啟明",
    "電力排碳係數",
    "內部碳定價",
    # Taiwan CBAM-exposed producers
    "台泥",
    "亞泥",
    "國產建材",

    # Japan & Korea
    "日本碳市場",
    "GX聯盟",
    "韓國碳排放交易",
    "K-ETS",
    "南韓碳市場",

    # VCM
    "自願性碳市場",
    "碳信用",
    "碳抵換",
    "碳權",
    "自願減量",

    # Article 6
    "巴黎協定碳交易",
    "第六條",

    # Cement, steel & hard-to-abate
    "鋼鐵減碳",
    "水泥減碳",
    "高碳排產業",
    "鋼鐵碳排",
    "綠色鋼鐵",
    "碳邊境 鋼鐵",
    "碳邊境 水泥",

    # CDR / nature
    "碳移除",
    "直接空氣捕捉",
    "自然碳匯",
    "森林碳匯",

    # CORSIA
    "航空碳抵換",
    "永續航空燃料",

    # India / emerging markets
    "印度碳市場",
    "印度碳邊境",
    "印度碳關稅",

    # Steel/metals (additional)
    "歐洲鋼鐵",
    "鋼鐵關稅",
    "低碳氫",
    "綠氫",
]

# ── Topic Classification ──────────────────────────────────────────────────────

TOPIC_PATTERNS: dict[str, list[str]] = {
    "EU CBAM — Policy & Implementation 歐盟CBAM政策": [
        "cbam", "carbon border adjustment", "carbon border mechanism",
        "carbon border tax", "cbam certificate", "cbam declarant",
        "cbam transitional", "cbam definitive", "cbam registry",
        "cbam reporting", "cbam scope", "cbam expansion",
        "embedded emissions", "cbam compliance", "cbam importer",
        "cbam equivalence", "cbam exemption",
        "free allocation", "mrv", "suspension clause",
        "downstream extension", "plastic cbam",
        "碳邊境調整機制", "碳邊境調節機制", "歐盟碳邊境", "碳關稅",
        "碳邊境調整", "碳邊境稅", "cbam憑證", "免費配額",
        "暫停條款", "下游擴展", "塑膠版cbam", "塑膠碳關稅",
    ],
    "EU ETS 歐盟碳交易": [
        "eu ets", "european emissions trading", "ets reform",
        "carbon allowance", "carbon permit", "eua price",
        "eu carbon market", "emissions trading scheme", "cap and trade",
        "歐盟碳排放交易", "碳排放配額", "碳交易體系",
    ],
    "UK Carbon Market 英國碳市場": [
        "uk ets", "uk emissions trading", "uk carbon market",
        "uk carbon price", "uk carbon border", "uk cbam",
        "英國碳邊境", "英國碳市場", "hmrc carbon",
    ],
    "Taiwan Carbon Market 台灣碳市場": [
        "taiwan carbon", "taiwan ets", "taiwan carbon fee",
        "tcx carbon", "taiwan carbon market",
        "碳邊境 出口", "碳邊境 鋼鐵", "碳邊境 鋁業",
        "台灣碳費", "台灣碳市場", "碳費", "台灣碳權交易所", "碳排放交易所",
        "碳盤查", "碳中和", "淨零碳排", "排碳",
    ],
    "Japan Carbon Market 日本碳市場": [
        "japan ets", "japan carbon market", "japan carbon pricing",
        "gx-ets", "gx league", "japan emissions trading",
        "日本碳市場", "GX聯盟",
    ],
    "Korea Carbon Market 韓國碳市場": [
        "korea ets", "k-ets", "south korea carbon",
        "korea carbon market", "korea emissions trading",
        "韓國碳排放交易", "K-ETS", "南韓碳市場",
    ],
    "Voluntary Carbon Market (VCM) 自願性碳市場": [
        "voluntary carbon market", "carbon credit", "carbon offset",
        "carbon registry", "icvcm", "ccp label", "core carbon principles",
        "verra", "gold standard", "carbon standard", "vcm",
        "自願性碳市場", "碳信用", "碳抵換", "碳權", "自願減量",
    ],
    "Article 6 & Paris Agreement 第六條": [
        "article 6", "paris agreement carbon", "itmos",
        "corresponding adjustment", "article 6.2", "article 6.4",
        "carbon crediting mechanism",
        "巴黎協定碳交易", "第六條",
    ],
    "CORSIA & Aviation 航空碳抵換": [
        "corsia", "aviation carbon", "aviation offset",
        "sustainable aviation fuel", "saf carbon", "icao carbon",
        "航空碳抵換", "永續航空燃料",
    ],
    "Carbon Removal & CDR 碳移除": [
        "carbon removal", "cdr", "direct air capture",
        "dac carbon", "biochar carbon", "enhanced weathering",
        "carbon dioxide removal",
        "碳移除", "直接空氣捕捉",
    ],
    "Nature-based Solutions 自然碳匯": [
        "nature-based carbon", "forest carbon", "redd+",
        "blue carbon", "soil carbon credit", "nature-based solution",
        "自然碳匯", "森林碳匯",
    ],
    "Cement, Steel & Hard-to-Abate Industry 水泥鋼鐵與高碳產業": [
        "cbam steel", "cbam aluminium", "cbam aluminum", "cbam cement",
        "cbam iron", "cbam fertiliser", "cbam fertilizer",
        "steel carbon", "cement carbon",
        "steel decarbonisation", "steel decarbonization",
        "cement decarbonisation", "cement decarbonization",
        "green steel", "hard-to-abate", "blast furnace",
        "electric arc furnace", "direct reduced iron", "dri steel",
        "eurofer", "carbon steel", "low-carbon steel", "low-carbon cement",
        "aluminium cbam", "aluminum cbam", "fertiliser cbam",
        "fertilizer cbam", "urea cbam", "hbi carbon", "norsk hydro",
        "tcc cement", "steel tariff", "aluminium tariff", "aluminum tariff",
        "鋼鐵減碳", "水泥減碳", "高碳排產業", "鋼鐵碳排",
        "鋁業碳關稅", "鋁cbam", "化肥碳費", "尿素碳稅",
        "台泥", "亞泥", "國產建材", "歐洲鋼鐵", "鋼鐵關稅",
    ],
    "Industry & Trade Response 產業與貿易回應": [
        "cbam industry", "carbon leakage",
        "cbam wto", "cbam challenge", "cbam retaliation",
        "carbon pricing equivalence", "cbam india", "cbam china",
        "cbam hydrogen", "hydrogen cbam", "trade carbon",
        "india cbam", "turkey ets", "australia carbon leakage",
        "印度碳市場", "印度碳邊境", "印度碳關稅",
        "碳洩漏",
    ],
    "Analysis & Research 分析與研究": [
        "carbon market report", "carbon market analysis",
        "cbam analysis", "carbon border study", "ercst",
        "carbon market review", "carbon pricing report",
    ],
}

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

# ── Utility Functions ─────────────────────────────────────────────────────────

def clean_html(raw: str) -> str:
    """Strip HTML tags and decode entities."""
    if not raw:
        return ""
    text = re.sub(r"<[^>]+>", " ", raw)
    text = html_module.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def matches_keywords(text: str) -> list[str]:
    """Return matched CBAM keywords found in combined article text."""
    if not text:
        return []
    text_lower = text.lower()
    matched: list[str] = []
    for kw in KEYWORDS_EN:
        if kw.lower() in text_lower:
            matched.append(kw)
    for kw in KEYWORDS_ZH:
        if kw in text:
            matched.append(kw)
    return list(dict.fromkeys(matched))  # preserve order, deduplicate


def classify_topic(matched_keywords: list[str]) -> str:
    """Assign article to the best-matching topic bucket."""
    scores: dict[str, int] = defaultdict(int)
    kw_lower = [k.lower() for k in matched_keywords]
    for topic, patterns in TOPIC_PATTERNS.items():
        for pat in patterns:
            if pat.lower() in kw_lower or any(pat.lower() in k for k in kw_lower):
                scores[topic] += 1
    # Also check raw keyword list for Chinese terms
    for kw in matched_keywords:
        for topic, patterns in TOPIC_PATTERNS.items():
            if kw in patterns:
                scores[topic] += 1
    if scores:
        return max(scores, key=scores.get)
    return "Other 其他"


def parse_rss_date(entry) -> datetime:
    """Parse publication date from a feedparser entry."""
    for field in ("published_parsed", "updated_parsed"):
        parsed = getattr(entry, field, None)
        if parsed:
            try:
                from time import mktime
                return datetime.fromtimestamp(mktime(parsed), tz=timezone.utc)
            except Exception:
                pass
    return datetime.now(tz=timezone.utc)


def make_article(
    source: str,
    source_type: str,
    title: str,
    summary: str,
    link: str,
    pub_date: "datetime | None",
    matched: list[str],
) -> dict:
    topic = classify_topic(matched)
    return {
        "source": source,
        "type": source_type,
        "title": title,
        "summary": summary[:MAX_SUMMARY_LEN] if source_type == "free" else "",
        "link": link,
        "published": pub_date.isoformat() if pub_date else "",
        "matched_keywords": matched[:8],
        "topic": topic,
    }


# ── Link Pattern Scraper helpers ─────────────────────────────────────────────

def _extract_article_title(soup) -> str:
    """Extract article title from a parsed article page."""
    # og:title is most reliable across both sites
    og = soup.find("meta", property="og:title")
    if og and og.get("content"):
        return og["content"].strip()
    # Fallback: first <h1>
    h1 = soup.find("h1")
    if h1:
        return h1.get_text(" ", strip=True)
    return ""


def _extract_article_date(soup) -> datetime | None:
    """
    Multi-fallback date extraction strategy:
      1. <meta property="article:published_time"> (most reliable)
      2. <meta name="date"> variants
      3. JSON-LD datePublished
      4. <time datetime="…"> attribute
      5. Regex on visible text "DD Month YYYY" / "Month DD, YYYY"
    Returns a UTC-aware datetime or None.
    """
    # 1. Open Graph article published time
    for prop in ("article:published_time", "og:article:published_time"):
        tag = soup.find("meta", property=prop)
        if tag and tag.get("content"):
            try:
                return datetime.fromisoformat(
                    tag["content"].replace("Z", "+00:00")
                ).astimezone(timezone.utc)
            except ValueError:
                pass

    # 2. <meta name="date"> variants
    for name in ("date", "publish_date", "published_time", "article:published"):
        tag = soup.find("meta", attrs={"name": name})
        if tag and tag.get("content"):
            try:
                return datetime.fromisoformat(
                    tag["content"].replace("Z", "+00:00")
                ).astimezone(timezone.utc)
            except ValueError:
                pass

    # 3. JSON-LD datePublished
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            import json as _json
            data = _json.loads(script.string or "")
            # Handle both single objects and @graph arrays
            if isinstance(data, dict):
                candidates = data.get("@graph", [data])
            else:
                candidates = data if isinstance(data, list) else [data]
            for item in candidates:
                if isinstance(item, dict) and item.get("datePublished"):
                    return datetime.fromisoformat(
                        item["datePublished"].replace("Z", "+00:00")
                    ).astimezone(timezone.utc)
        except Exception:
            pass

    # 4. <time datetime="…">
    time_tag = soup.find("time", attrs={"datetime": True})
    if time_tag:
        try:
            return datetime.fromisoformat(
                time_tag["datetime"].replace("Z", "+00:00")
            ).astimezone(timezone.utc)
        except ValueError:
            pass

    # 5. Short standalone date elements — e.g. Sylvera's
    #    <div class="text-size-regular_16px">May 22, 2026</div>
    #    Match elements whose entire text content is a date, not buried in prose.
    date_only_pat = re.compile(
        r"^\s*(\d{1,2}\s+\w+\s+\d{4}|\w+\s+\d{1,2},?\s+\d{4})\s*$"
    )
    for tag in soup.find_all(["div", "span", "p"]):
        text = tag.get_text(" ", strip=True)
        m = date_only_pat.match(text)
        if m:
            raw = m.group(1).replace(",", "").strip()
            for fmt in ("%d %B %Y", "%B %d %Y"):
                try:
                    dt = datetime.strptime(raw, fmt)
                    return dt.replace(tzinfo=timezone.utc)
                except ValueError:
                    pass

    return None


def _extract_article_summary(soup) -> str:
    """
    Extract a plain-text summary from an article page.
    Priority: og:description → meta description → first <p> in main content.
    """
    # og:description
    og = soup.find("meta", property="og:description")
    if og and og.get("content"):
        return og["content"].strip()[:MAX_SUMMARY_LEN]

    # <meta name="description">
    meta_desc = soup.find("meta", attrs={"name": "description"})
    if meta_desc and meta_desc.get("content"):
        return meta_desc["content"].strip()[:MAX_SUMMARY_LEN]

    # First substantive <p> in <article>, <main>, or <body>
    for container_tag in ("article", "main", "body"):
        container = soup.find(container_tag)
        if container:
            for p in container.find_all("p"):
                text = p.get_text(" ", strip=True)
                if len(text) > 60:
                    return text[:MAX_SUMMARY_LEN]

    return ""


def fetch_link_pattern_source(
    source_name: str,
    config: dict,
    cutoff: datetime,
    seen_urls: set,
    debug: bool = False,
) -> list[dict]:
    """
    Scrape a site with no RSS. Two URL-discovery modes:

    Sitemap mode (config has 'sitemap_url'):
      Parses sitemap XML for article URLs + lastmod dates. More reliable than
      scraping listing pages that use client-side rendering.

    Listing-page mode (config has 'listing_url'):
      Fetches the listing page and collects article hrefs by regex pattern.
    """
    if not HAS_REQUESTS:
        print(f"  [WARN] requests/BeautifulSoup not installed — skipping {source_name}", file=sys.stderr)
        return []

    source_type      = config["type"]
    base_url         = config.get("base_url", "")
    link_pat         = config["link_pattern"]
    skip_date_filter = config.get("skip_date_filter", False)
    keep_query_string = config.get("keep_query_string", False)
    articles: list[dict] = []

    # ── Mode A: sitemap-based URL discovery ──────────────────────────────
    if "sitemap_url" in config:
        try:
            r = requests.get(config["sitemap_url"], headers=HTTP_HEADERS, timeout=REQUEST_TIMEOUT)
            r.raise_for_status()
        except Exception as e:
            print(f"  [WARN] Could not fetch sitemap for {source_name}: {e}", file=sys.stderr)
            return []

        sitemap_soup = BeautifulSoup(r.content, "html.parser")
        candidates: list[tuple[str, str, datetime | None]] = []  # (url, title_hint, lastmod)
        for url_tag in sitemap_soup.find_all("url"):
            loc = url_tag.find("loc")
            lastmod_tag = url_tag.find("lastmod")
            if not loc:
                continue
            full_url = loc.text.strip()
            if not link_pat.match(full_url) or full_url in seen_urls:
                continue
            lastmod: datetime | None = None
            if lastmod_tag:
                try:
                    lastmod = datetime.fromisoformat(
                        lastmod_tag.text.strip().replace("Z", "+00:00")
                    ).astimezone(timezone.utc)
                except ValueError:
                    pass
            candidates.append((full_url, "", lastmod))

        # Sort by lastmod descending (most recent first); unknowns go last
        candidates.sort(key=lambda x: x[2] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        print(f"    sitemap: {len(candidates)} candidate URLs found", file=sys.stderr)

        fetched = 0
        for article_url, _, lastmod in candidates:
            if fetched >= MAX_DETAIL_FETCHES:
                break
            # Use lastmod as quick date filter before fetching the page
            if not skip_date_filter and lastmod and lastmod < cutoff:
                if debug:
                    print(f"      [DEBUG] too old (lastmod): {article_url} ({lastmod.date()})", file=sys.stderr)
                continue

            time.sleep(SCRAPE_DELAY)
            try:
                ar = requests.get(article_url, headers=HTTP_HEADERS, timeout=REQUEST_TIMEOUT)
                ar.raise_for_status()
            except Exception as e:
                if debug:
                    print(f"      [DEBUG] fetch failed {article_url}: {e}", file=sys.stderr)
                continue

            fetched += 1
            asoup = BeautifulSoup(ar.text, "html.parser")
            title   = _extract_article_title(asoup) or ""
            summary = _extract_article_summary(asoup)
            pub_date = lastmod or _extract_article_date(asoup)
            if pub_date is None and not skip_date_filter:
                continue  # no date on a non-portal item → treat as stale

            if not title:
                continue

            search_text = f"{title} {summary}"
            matched = matches_keywords(search_text)

            if not matched:
                if debug:
                    print(f"      [DEBUG] no keyword match: {title[:80]}", file=sys.stderr)
                continue

            seen_urls.add(article_url)
            articles.append(make_article(
                source_name, source_type, title, summary, article_url, pub_date, matched
            ))

        print(
            f"    fetched {fetched} pages → {len(articles)} matched",
            file=sys.stderr,
        )
        return articles

    # ── Mode B: listing-page URL discovery ───────────────────────────────
    listing_url = config["listing_url"]

    try:
        r = requests.get(listing_url, headers=HTTP_HEADERS, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
    except Exception as e:
        print(f"  [WARN] Could not fetch listing page for {source_name}: {e}", file=sys.stderr)
        return []

    soup = BeautifulSoup(r.text, "html.parser")

    candidates_b: list[tuple[str, str]] = []   # (full_url, anchor_text)
    seen_hrefs: set = set()
    for a_tag in soup.find_all("a", href=True):
        href: str = a_tag["href"].strip()
        if keep_query_string:
            href = href.split("#")[0]  # keep ?query, strip #fragment only
        else:
            href = href.split("?")[0].split("#")[0].rstrip("/")
        if not href or href in seen_hrefs:
            continue
        if link_pat.match(href):
            # Support both absolute hrefs (http://…) and relative paths (/slug)
            full_url = href if href.startswith("http") else base_url + href
            if full_url not in seen_urls:
                anchor_text = a_tag.get_text(" ", strip=True)
                candidates_b.append((full_url, anchor_text))
                seen_hrefs.add(href)

    print(f"    listing: {len(candidates_b)} candidate links found", file=sys.stderr)

    if not candidates_b:
        return []

    # ── Step 3: keyword-filter on anchor text first ───────────────────────
    kw_filtered: list[tuple[str, str]] = []
    title_matched: list[tuple[str, str]] = []
    for url, anchor in candidates_b:
        if matches_keywords(anchor):
            title_matched.append((url, anchor))
        else:
            kw_filtered.append((url, anchor))

    # Process keyword-matched titles first, then remaining (in case dates are recent)
    ordered = title_matched + kw_filtered

    # ── Step 4: fetch individual article pages ────────────────────────────
    date_from_url_pat = config.get("date_from_url_regex")
    fetched = 0
    for article_url, anchor_text in ordered:
        if fetched >= MAX_DETAIL_FETCHES:
            break

        # Pre-filter by date embedded in URL (avoids fetching old pages)
        url_pub_date: datetime | None = None
        if date_from_url_pat:
            m = re.search(date_from_url_pat, article_url)
            if m:
                try:
                    url_pub_date = datetime.strptime(
                        m.group("date"), "%Y%m%d"
                    ).replace(tzinfo=timezone.utc)
                    if not skip_date_filter and url_pub_date < cutoff:
                        if debug:
                            print(f"      [DEBUG] too old (url date): {article_url}", file=sys.stderr)
                        continue
                except Exception:
                    pass

        time.sleep(SCRAPE_DELAY)
        try:
            ar = requests.get(article_url, headers=HTTP_HEADERS, timeout=REQUEST_TIMEOUT)
            ar.raise_for_status()
        except Exception as e:
            if debug:
                print(f"      [DEBUG] fetch failed {article_url}: {e}", file=sys.stderr)
            continue

        fetched += 1
        asoup = BeautifulSoup(ar.text, "html.parser")

        # Date check — skip articles outside lookback window (unless skip_date_filter set)
        pub_date = _extract_article_date(asoup) or url_pub_date
        if pub_date is None:
            if not skip_date_filter:
                if debug:
                    print(f"      [DEBUG] no date found, skipping: {article_url}", file=sys.stderr)
                continue  # no date on a non-portal item → treat as stale
        elif not skip_date_filter and pub_date < cutoff:
            if debug:
                print(f"      [DEBUG] too old: {article_url} ({pub_date.date()})", file=sys.stderr)
            continue

        title   = _extract_article_title(asoup) or anchor_text or ""
        summary = _extract_article_summary(asoup)

        if not title:
            continue

        search_text = f"{title} {summary}"
        matched = matches_keywords(search_text)

        if not matched:
            if debug:
                print(f"      [DEBUG] no keyword match: {title[:80]}", file=sys.stderr)
            continue

        seen_urls.add(article_url)
        articles.append(make_article(
            source_name, source_type, title, summary, article_url, pub_date, matched
        ))

    n_kw = len(title_matched)
    print(
        f"    fetched {fetched} pages ({n_kw} keyword-matched titles) → "
        f"{len(articles)} matched",
        file=sys.stderr,
    )
    return articles


# ── RSS Fetcher ───────────────────────────────────────────────────────────────

def fetch_rss_source(
    source_name: str,
    config: dict,
    cutoff: datetime,
    seen_urls: set,
    debug: bool = False,
) -> list[dict]:
    if not HAS_FEEDPARSER:
        return []

    source_type = config["type"]
    extra_headers = config.get("feedparser_headers", {})
    articles: list[dict] = []

    for feed_url in config["feeds"]:
        try:
            feed = feedparser.parse(feed_url, request_headers=extra_headers)
            if feed.bozo and not feed.entries:
                print(f"  [WARN] Malformed or empty feed: {feed_url}", file=sys.stderr)
                continue

            n_entries = len(feed.entries)
            n_recent = 0
            n_matched = 0
            debug_misses = []

            for entry in feed.entries:
                link = entry.get("link", "").strip()
                if not link or link in seen_urls:
                    continue

                title = clean_html(entry.get("title", ""))
                if not title:
                    continue

                pub_date = parse_rss_date(entry)
                if pub_date < cutoff:
                    continue
                n_recent += 1

                summary = clean_html(
                    entry.get("summary", entry.get("description", ""))
                )
                content = ""
                if entry.get("content"):
                    content = clean_html(entry.content[0].get("value", ""))
                tags = " ".join(
                    clean_html(t.get("term", "") or t.get("label", ""))
                    for t in entry.get("tags", [])
                )

                search_text = f"{title} {summary} {content} {tags}"
                matched = matches_keywords(search_text)

                if not matched:
                    if debug and len(debug_misses) < 3:
                        debug_misses.append({
                            "title": title,
                            "summary": summary[:120],
                            "tags": tags[:120],
                        })
                    continue

                n_matched += 1
                seen_urls.add(link)
                articles.append(make_article(
                    source_name, source_type, title, summary, link, pub_date, matched
                ))

            feed_label = feed_url.split("//")[-1].split("?")[0][:60]
            print(
                f"    {feed_label}: {n_entries} entries, "
                f"{n_recent} recent, {n_matched} matched",
                file=sys.stderr,
            )

            if debug and debug_misses and n_matched == 0 and n_recent > 0:
                print(f"    [DEBUG] Sample unmatched entries:", file=sys.stderr)
                for m in debug_misses:
                    print(f"      title:   {m['title']}", file=sys.stderr)
                    print(f"      summary: {m['summary']}", file=sys.stderr)
                    print(f"      tags:    {m['tags']}", file=sys.stderr)
                    print(f"      ---", file=sys.stderr)

        except Exception as e:
            print(f"  [WARN] RSS fetch failed for {feed_url}: {e}", file=sys.stderr)

    return articles


# ── Main Aggregator ───────────────────────────────────────────────────────────

def fetch_all(
    hours_lookback: int = 168,
    debug: bool = False,
) -> list[dict]:
    """Fetch from all sources and return deduplicated, keyword-filtered articles."""
    cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=hours_lookback)
    seen_urls: set = set()
    all_articles: list[dict] = []

    for source_name, config in RSS_FEEDS.items():
        print(f"[RSS] {source_name}...", file=sys.stderr)
        articles = fetch_rss_source(source_name, config, cutoff, seen_urls, debug=debug)
        print(f"      → {len(articles)} matched", file=sys.stderr)
        all_articles.extend(articles)

    for source_name, config in LINK_PATTERN_SOURCES.items():
        source_label = config.get("sitemap_url", config.get("listing_url", ""))
        print(f"[SCRAPE] {source_name} ({source_label})...", file=sys.stderr)
        articles = fetch_link_pattern_source(
            source_name, config, cutoff, seen_urls, debug=debug
        )
        print(f"         → {len(articles)} matched", file=sys.stderr)
        all_articles.extend(articles)

    all_articles.sort(key=lambda a: a["published"], reverse=True)

    print(
        f"\n[DONE] {len(all_articles)} total matched articles "
        f"(lookback: {hours_lookback}h, cutoff: {cutoff.strftime('%Y-%m-%d %H:%M UTC')})",
        file=sys.stderr,
    )
    return all_articles


# ── Newsletter Formatters ─────────────────────────────────────────────────────

def format_html(articles: list[dict], run_time: str) -> str:
    """Two-tier HTML: executive summary at top, full jurisdiction sections below."""
    from collections import defaultdict

    by_topic: dict[str, list] = defaultdict(list)
    for a in articles:
        by_topic[a["topic"]].append(a)

    # ── Executive Summary — one lead item per non-empty topic (up to 6) ──
    key_items = []
    for topic in TOPIC_ORDER:
        items = by_topic.get(topic, [])
        if items:
            key_items.append((topic, items[0]))
        if len(key_items) >= 6:
            break

    summary_rows = ""
    for topic, a in key_items:
        # Short topic label (everything before "—" or first space run)
        short_topic = topic.split("—")[0].strip().split(" ")[0]
        # Pull first sentence of summary for free sources
        excerpt = ""
        if a["type"] == "free" and a["summary"]:
            first_sent = re.split(r"(?<=[.!?])\s", a["summary"])
            excerpt = first_sent[0] if first_sent else a["summary"][:120]
            excerpt = f'<span style="color:#555;"> — {excerpt}</span>'
        summary_rows += f"""
        <div style="padding:7px 0;border-bottom:1px solid #e8f5e9;">
          <span style="display:inline-block;background:#e8f5e9;color:#2e7d32;
            font-size:11px;font-weight:600;padding:2px 7px;border-radius:10px;
            margin-right:8px;white-space:nowrap;">{short_topic}</span>
          <a href="{a['link']}" style="color:#1a0dab;font-size:14px;
             text-decoration:none;font-weight:600;">{a['title']}</a>
          {excerpt}
          <br/>
          <span style="color:#999;font-size:11px;margin-left:4px;">
            {a['source']} &middot; {a['published'][:10]}
          </span>
        </div>"""

    exec_summary = f"""
    <div style="margin:20px 0 28px 0;background:#f9fbe7;border-left:4px solid #2e7d32;
         border-radius:4px;padding:14px 18px;">
      <h2 style="margin:0 0 12px 0;font-size:16px;color:#1b5e20;letter-spacing:.3px;">
        Key Developments This Week
      </h2>
      {summary_rows}
    </div>"""

    # ── Full topic sections ───────────────────────────────────────────────
    sections_html = ""
    for topic in TOPIC_ORDER:
        items = by_topic.get(topic, [])
        if not items:
            continue

        rows = ""
        for a in items:
            kw_tags = " ".join(
                f'<span style="background:#e8f5e9;color:#2e7d32;padding:2px 6px;'
                f'border-radius:3px;font-size:11px;margin-right:4px;">{k}</span>'
                for k in a["matched_keywords"][:5]
            )
            summary_block = ""
            if a["type"] == "free" and a["summary"]:
                summary_block = (
                    f'<p style="color:#444;font-size:14px;margin:4px 0 6px 0;">'
                    f'{a["summary"]}</p>'
                )
            else:
                summary_block = (
                    '<p style="color:#999;font-size:13px;font-style:italic;'
                    'margin:4px 0 6px 0;">Full text behind paywall — headline only.</p>'
                )
            rows += f"""
            <div style="padding:10px 0 6px 0;">
              <a href="{a['link']}" style="color:#1a0dab;font-size:15px;
                 text-decoration:none;font-weight:600;">{a['title']}</a><br/>
              <span style="color:#888;font-size:12px;">
                {a['source']} &middot; {a['published'][:10]}
              </span>
              {summary_block}
              <div style="margin-top:4px;">{kw_tags}</div>
            </div>
            <div style="border-bottom:1px solid #eee;"></div>"""

        sections_html += f"""
        <div style="margin-bottom:28px;">
          <h2 style="color:#202124;font-size:17px;border-bottom:2px solid #2e7d32;
              padding-bottom:6px;margin-bottom:10px;">{topic}
            <span style="font-size:13px;color:#888;font-weight:normal;">
              ({len(items)})</span>
          </h2>
          {rows}
        </div>"""

    total = len(articles)
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,
  Helvetica,Arial,sans-serif;max-width:680px;margin:0 auto;padding:16px;
  color:#202124;background:#fff;">

  <div style="text-align:center;padding:16px 0;border-bottom:3px solid #2e7d32;">
    <h1 style="margin:0;font-size:22px;color:#202124;">
      CBAM Global Monitor<br/>
      <span style="font-size:16px;color:#555;">碳邊境調整機制週報</span>
    </h1>
    <p style="margin:8px 0 0 0;color:#666;font-size:13px;">
      {run_time} &middot; {total} articles
    </p>
  </div>

  {exec_summary}

  {sections_html}

  <div style="text-align:center;padding:16px 0;border-top:1px solid #ddd;
       color:#999;font-size:11px;">
    Carbon Markets Global Monitor &middot; Weekly Edition<br/>
    Sources: Euractiv · Carbon Brief · Carbon Pulse · Carbon Market Watch ·
    Climate Home News · Politico Europe · E3G · Sandbag · Clear Blue Markets ·
    EU Council · EUROMETAL · SteelOrbis · GMK Center · Carbon Credits ·
    Business Standard India · NDTV Profit India ·
    Ember Energy · Sylvera · BeZero Carbon · DG TAXUD CBAM · 今週刊 ESG · 天下雜誌 ·
    經貿透視 Trademag · CNA · UDN · Economic Daily · 環境資訊中心 ·
    FT · Nikkei Asia · Bloomberg Green · S&P Commodity Insights
  </div>
</body></html>"""


def format_markdown(articles: list[dict], run_time: str) -> str:
    by_topic: dict[str, list] = defaultdict(list)
    for a in articles:
        by_topic[a["topic"]].append(a)

    lines = [
        "# CBAM Global Monitor 碳邊境調整機制週報",
        f"**Generated**: {run_time}",
        f"**Articles**: {len(articles)}",
        "",
    ]

    for topic in TOPIC_ORDER:
        items = by_topic.get(topic, [])
        if not items:
            continue
        lines.append(f"## {topic} ({len(items)})")
        lines.append("")
        for a in items:
            kw = ", ".join(a["matched_keywords"][:5])
            lines.append(f"### [{a['title']}]({a['link']})")
            lines.append(f"**{a['source']}** | {a['published'][:10]} | {kw}")
            if a["type"] == "free" and a["summary"]:
                lines.append(f"\n{a['summary']}")
            lines.extend(["", "---", ""])

    return "\n".join(lines)


# ── Entry Point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="CBAM Global Monitor — RSS News Aggregator"
    )
    parser.add_argument(
        "--hours", type=int, default=168,
        help="Look back this many hours (default: 168 = 7 days)"
    )
    parser.add_argument(
        "--format", choices=["html", "markdown", "json"], default="html",
        help="Output format (default: html)"
    )
    parser.add_argument(
        "--output", type=str, default=None,
        help="Output file path (default: stdout)"
    )
    parser.add_argument(
        "--debug", action="store_true",
        help="Print sample unmatched entries to help diagnose keyword gaps"
    )
    args = parser.parse_args()

    run_time = datetime.now(tz=timezone(timedelta(hours=8))).strftime(
        "%Y-%m-%d %H:%M (Taipei)"
    )

    articles = fetch_all(
        hours_lookback=args.hours,
        debug=args.debug,
    )

    if args.format == "json":
        output = json.dumps(articles, ensure_ascii=False, indent=2)
    elif args.format == "markdown":
        output = format_markdown(articles, run_time)
    else:
        output = format_html(articles, run_time)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output)
        print(f"[OUT] Saved to {args.output}", file=sys.stderr)
    else:
        print(output)
