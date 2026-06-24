# 國際新聞蒐集 — RADAR + Weekly Collector (authoritative workflow)

**This file is the single source of truth for the `cbam-weekly-news` Cowork skill.**
The skill is a thin shell that fetches this file and follows it. To change the workflow,
edit **this file in the cbam-monitor repo and commit** — do **not** edit the skill (managed-skill
edits are wiped by the next server sync, and they diverge per machine).

Raw URL the skill fetches:
`https://raw.githubusercontent.com/alamarisco/cbam-monitor/main/WORKFLOW.md`

Daily triage and weekly compilation for the 產品碳洩漏管理與公眾溝通計畫 international news brief.
News is collected by CI continuously, alerted to the LINE group as it is picked, translated into
the **living weekly doc**, and finalized as a dated `.docx` each week.

---

## Account constants

| Key | Value |
|---|---|
| Repo slug | `alamarisco/cbam-monitor` |
| Drive folder — weekly docs `國際新聞蒐集/2026年/` | `1dwXqv1UMclM1Ni3CIPBMBo62X-W58aFr` |
| Drive folder — state `國際新聞蒐集/_state/` | `1DKzbo0r0j_7jQmPd9dzB8fTNtMA5RhTX` |

**Script & reference paths** below (e.g. `scripts/append_story.py`, `reference/streams.md`,
`templates/weekly_template.docx`) are **relative to the skill directory** (`cbam-weekly-news/`),
which ships the docx tooling. Resolve them there.

---

## Three modes

| Mode | When | What it does |
|---|---|---|
| **RADAR** | daily ("run the radar", "今天有什麼CBAM新聞") | Fetch the **CI-built** triage page and present it. No script execution, no portal diffing, no translation. |
| **FLAG** | when the user picks items (or pastes a link) | Translate (house style), emit a paste-ready 中文 LINE message, append to the living weekly doc, log the pick, update the ledger via GitHub dispatch. |
| **COMPILE** | end of week | Top-up sweep, verify, finalize the dated `.docx` in Drive `2026年/`. |

---

## Architecture (read once)

- **CI is the engine.** The cbam-monitor GitHub Action (`daily-data.yml`) runs every weekday
  16:07 Taipei + Monday catch-up. It fetches all feeds (including EU `DG TAXUD CBAM` and
  `UK CBAM Portal` sources), runs `radar/scripts/radar_process.py` with portal dedup + staleness
  filtering, and commits the finished triage HTML to the repo. **You do not re-run any of this.**
- **Do NOT run `radar_process.py` locally.** If you find a copy bundled in the skill folder,
  ignore it — it is stale and unused. RADAR = fetch the artifact CI already built.
- **The dedup ledger is `state/seen_urls.json` in the repo**, not Drive. RADAR dedup is applied
  by CI; FLAG appends to it via the `flag-pick` dispatch (below). The Drive `_state/seen_urls.json`
  is deprecated — do not read or write it.

---

## RADAR mode (daily)

### R1 — Find today's triage (web_fetch)
`web_fetch` → `https://raw.githubusercontent.com/alamarisco/cbam-monitor/main/data/radar/index.json`
It returns `{"date","triage_dated","built_at"}`. Use `triage_dated` to fetch the dated file
(more cache-stable than `triage_latest.html`):
`https://raw.githubusercontent.com/alamarisco/cbam-monitor/main/data/radar/<triage_dated>`

Sanity-check `built_at` and `date` are today (Taipei). If they're stale (>1 day old), the
Action may have been skipped — see the fallback below.

### R2 — Present the triage page
Pass the fetched HTML straight to `create_artifact`. It shows Stream A grouped by tier
(🔴TOP / 🟠HIGH / 🟡MED, TOP+HIGH pre-checked) with a "Send selection to Claude" button, and
Stream B as a collapsed reference list. The user ticks what they want and clicks send — that
returns the picks and triggers FLAG mode.

### R3 — (optional) machine-readable candidates
If you need structured data (counts, summaries), also `web_fetch`
`.../data/radar/candidates.json`. Do not rebuild it.

### Fallback — if the triage is stale or empty
The Action emails a "Daily Data Feed: all jobs have failed" notice on failure. If today's
triage is missing/stale: (a) check the **CBAM Global Monitor 碳邊境調整機制週報** email digest in
Gmail (`CBAM Global Monitor newer_than:2d`) and parse its article list as the candidate pool,
and/or (b) `web_fetch` the EU/UK official portals directly:
- EU — `https://taxation-customs.ec.europa.eu/carbon-border-adjustment-mechanism_en`
- UK — `https://www.gov.uk/government/collections/carbon-border-adjustment-mechanism`
Dedup against `.../state/seen_urls.json`, then present manually. This is a rare degraded mode.

### Date-verification (REQUIRED before anything is shortlisted)
CI dates are usually reliable, but if a date looks off, `web_fetch` the article and confirm
`meta article:published_time` before keeping it. (See COMPILE Step 2.5 traps — republish ≠
original date.)

---

## FLAG mode (on pick — one article at a time)

For each picked URL:

0. **Resolve an openable source first (paywalled picks).** Several feeds give a headline +
   short summary but lock the full article: **Carbon Pulse**, Financial Times, Nikkei Asia,
   Bloomberg, and sometimes S&P Global. If the picked item is from one of these (or any page you
   cannot fully read), do **not** translate from the snippet — `WebSearch` the same story from an
   openable outlet and switch to it before translating:
   - Search the headline's key facts (e.g. `EU CBAM draft rules onerous importers June 2026`),
     preferring `reference/sources.md` names that are openable: GMK Center, S&P Global (free
     items), Euractiv, EUROMETAL, Reuters/AP reprints, Argus, Montel, official EU/UK pages.
   - **Verify it's the same story, not just the same topic:** same event/announcement, same key
     figures, and a publication date within ~1–2 days of the Carbon Pulse item (watch the
     republish-date trap in COMPILE Step 2.5).
   - Translate, cite (`新聞出處`/LINE 來源), and ledger the **openable** URL. Add the original
     Carbon Pulse URL to the dedup ledger too (FLAG step 5) so it won't resurface.
   - If no openable equivalent exists, translate from the Carbon Pulse headline + summary only,
     keep it short, and note `（僅摘要，原文需訂閱）` so Alec knows it's snippet-based.

1. **Translate** to Traditional Chinese, ESTC house style, full article (not a summary).
   For multi-section pieces, use **bold sub-headers** — but **do NOT bold body text**. Keep
   figures, company names, official titles, CN codes accurate.
   - **Body:** acronyms (CBAM, EU ETS, MRV, CSCF, TRQ) may stay in Latin on first mention with a
     Chinese gloss.
   - **Titles — no acronyms.** In both the `# headline` and the LINE `中文標題`, spell every term
     out in full Chinese: 碳邊境調整機制 (not CBAM), 歐盟排放交易體系 (not EU ETS), 監測、報告與查證
     (not MRV). Organisation names use the full Chinese name — e.g. 歐洲汽車供應商協會 (not CLEPA),
     歐洲鋼鐵協會 (not EUROFER), 美國戰略暨國際研究中心 (not CSIS). Acronyms may appear later in the body.

2. **Paste-ready LINE message** (Alec copies this into the LINE group):
   ```
   【CBAM新聞】<中文標題>
   重點：<一到兩句中文重點>
   來源：<媒體>｜<YYYY/MM/DD>
   <URL>
   ```

3. **Append to the living weekly `.docx`** (Drive connector → local → Drive):
   - Download the most recent `.docx` from Drive folder `1dwXqv1UMclM1Ni3CIPBMBo62X-W58aFr` to
     `/tmp/weekly.docx` (or seed a fresh week by copying `templates/weekly_template.docx` — never
     a blank `Document`, or the page-1 index table and page-number footer go missing).
   - Write the translation to `/tmp/content.txt`: `# headline`, `## sub-header`, plain body lines,
     `SRC <url>`, `DATE <YYYY/MM/DD>`.
   - Run `python scripts/append_story.py /tmp/weekly.docx /tmp/content.txt /tmp/weekly_out.docx`.
     It adds a hyperlinked **項次 row** to the index table, inserts a **page break**, applies the
     item house style (新聞標題 auto-numbered 24pt; body/sub-headers Times New Roman + 標楷體 14pt,
     23pt exact line spacing, 9pt space-before; sub-headers bold, **body never bold**), and
     recalculates `本週共計 N 則`. (`scripts/build_docx.py` is for a full from-scratch rebuild only.)
   - Re-upload `/tmp/weekly_out.docx` to Drive folder `1dwXqv1UMclM1Ni3CIPBMBo62X-W58aFr`.

4. **Log the pick to the queue.** Run `python scripts/flag_article.py --root "<Drive root local
   path>" --week <MM.DD-MM.DD> --url URL --source S --date YYYY/MM/DD --by "Claude"
   --headline "中文標題"`, then upload the updated `_queue_<week>.md` to Drive `_state/`.

5. **Update the dedup ledger** via GitHub dispatch (no local clone; works from any machine):
   ```
   curl -X POST \
     -H "Authorization: Bearer $(gh auth token)" \
     -H "Content-Type: application/json" \
     https://api.github.com/repos/alamarisco/cbam-monitor/dispatches \
     -d '{"event_type":"flag-pick","client_payload":{"urls":["<URL>"]}}'
   ```
   Requires `gh` authenticated on this machine (`gh auth status`). If `gh` is unavailable,
   substitute `$CBAM_GH_TOKEN` (fine-grained PAT, Contents: read/write on `cbam-monitor`). The
   `flag-pick.yml` Action appends the URL to `state/seen_urls.json` and commits automatically.

Skip silently if the URL is already in the ledger or queue.

---

## COMPILE mode (weekly finalize)

The living doc is already mostly built, so this is a light pass.

### Step 1 — Establish the week & dedupe set
Download the most recent `.docx` from Drive `2026年/` to find the previous end date. Coverage
window starts the day AFTER it (includes the weekend) through this file's end date. Filename label
follows `MM.DD-MM.DD` (weekdays). Build the dedupe set from `.../state/seen_urls.json` plus the
previous 4–6 weekly files (`scripts/extract_prior_urls.py`).

### Step 2 — Top-up sweep
Read `stories_<week>.json` from Drive `_state/`. Optionally `web_fetch` tracked sources in
`reference/sources.md` for anything missed, date-restricted. A bare "CBAM" search is not
sufficient — many in-scope stories (EU ETS, 免費配額, steel safeguard, Taiwan 碳費/電力排碳係數,
塑膠版CBAM, India–EU FTA) never contain the literal "CBAM". Drop anything in the dedupe set.

### Step 2.5 — Verify every new candidate's date (REQUIRED)
`web_fetch` and read the real `published_time` before shortlisting. Traps: republish/aggregator
date ≠ original (EUROMETAL republishes SteelOrbis/Kallanish days later); a 「…13日」 headline is an
event day, not the publication month; cross-check substance against recent editions, not the URL.

### Step 2.6 — Prefer a reliable, openable source
When a story runs across outlets, choose the most reliable openable version (prefer
`reference/sources.md`: GMK Center, S&P Global, Carbon Pulse, Euractiv, EUROMETAL). Avoid
SEO/crypto reposts. Use that source's own date.

### Steps 3–6 — Translate top-ups, assemble, verify, upload
Build on `templates/weekly_template.docx` and append with `scripts/append_story.py` (preferred),
or full-rebuild with `scripts/build_docx.py` reproducing the House style below. Verify: every
story has a working `新聞出處` URL + confirmed `日期`; no duplicates; `本週共計 N 則` matches the
count; the page-1 index table has one hyperlinked row per story; the footer shows page numbers;
spot-check 1–2 translations. Upload to Drive `2026年/`, remind Alec to copy it to the company
Drive, and present with `present_files`.

### House style
Every weekly is built on **`templates/weekly_template.docx`** (page-1 title block + empty 項次
index table + centred page-number footer + the `新聞標題` numbered-list style already defined).
Seed each new week by copying the template, then add stories with `scripts/append_story.py`.

**Page 1, top (in order):**

| Element | Font | Size | Bold |
|---|---|---|---|
| Title line 1 `產品溫室氣體排放強度建立及碳邊境調整機制推動計畫` | 標楷體 / Times New Roman | 18pt | yes |
| Title line 2 `因應計畫內容蒐集國際間最新推動資訊定期更新` | 標楷體 / Times New Roman | 18pt | yes |
| Date line `YYYY年M月D日更新` | 標楷體 / Times New Roman | 14pt | no |
| Count line `本週共計 N 則` (則 bold) | 標楷體 / Times New Roman | 16pt | 則 only |

**Index table** (`項次` | `標題`), directly under the count line on page 1:
- 2-column table, 24pt exact line spacing, cells vertically centred.
- Header row `項次` / `標題`: centred, **bold**, 16pt 標楷體.
- One data row per story: `項次` centred non-bold 16pt; `標題` left-aligned, rendered as an
  **internal hyperlink** (colour `0563C1`, single underline) jumping to that article's headline
  (bookmark `art<N>`). Column widths ≈ 988 / 8646 dxa.

**Each article:**
- Starts on a **new page** (page break before every article, including the first).
- Headline: style `新聞標題`, **auto-numbered** (1, 2, 3 …), 24pt exact line spacing. No acronyms.
- Sub-headers: 標楷體 / Times New Roman 14pt **bold**, 23pt exact line spacing, 9pt space-before.
- Body / `新聞出處：<url>` / `日期：<YYYY/MM/DD>`: 14pt, 23pt exact line spacing, **never bold**,
  no first-line indent.

**Footer (every page):** centred page number — a `PAGE \* MERGEFORMAT` field.

---

## Priority model (used by CI's RADAR ranking — reference only)

- **🔴 TOP** — any NEW EU/UK official-portal item.
- **🟠 HIGH** — EU CBAM policy · **UK CBAM policy** · Taiwan exposure (碳費, 電力排碳係數,
  steel/cement/aluminium exporters) · covered goods (鋼鐵/水泥/鋁/化肥/氫/塑膠版CBAM) · industry
  & trade response · WTO & third-country (India, China, Turkey).
- **🟡 MED** — tangential CBAM mentions, market-price notes, secondary commentary.
- **Stream B (reference only, NOT triaged)** — VCM, compliance markets, CORSIA, CDR, Article 6,
  nature-based, Japan/Korea domestic ETS. Listed for research; never alerted or added to the
  weekly doc.

See `reference/streams.md`, `reference/sources.md`, `reference/keywords.md` (in the skill) for
the full bucket → stream/tier mapping, tracked sources, and bilingual keyword set.
