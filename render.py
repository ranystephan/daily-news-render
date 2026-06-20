#!/usr/bin/env python3
"""
Daily headline lock-screen wallpaper renderer.

Fetches three sections — World news, Research (arXiv), and Markets/finance —
and renders a 1320x2868 PNG sized for the iPhone 17 Pro Max lock screen.
The top portion of the image is left empty for the iOS clock and widgets.

Run normally:        python render.py
Preview offline:     python render.py --selftest     (uses sample data, no network)
"""

import os
import sys
import json
import html
import socket
import datetime
import urllib.request
from zoneinfo import ZoneInfo

import feedparser

# ----------------------------------------------------------------------------
# CONFIG  — edit these
# ----------------------------------------------------------------------------
TIMEZONE = "America/Los_Angeles"     # your local zone (used for the date/time stamp)
WIDTH, HEIGHT = 1320, 2868           # iPhone 17 Pro Max, in pixels
CLOCK_ZONE = 0.36                    # top fraction left empty for the iOS clock
OUTPUT = "headlines.png"

# How many items to show per section (tune to taste / fit).
ITEMS = {"World": 2, "Research": 3, "Markets": 3}

# Max characters per headline before it's trimmed (research titles run long).
MAX_CHARS = {"World": 92, "Research": 86, "Markets": 92}

# News feeds: (url, short source label). Listed best-first; failures are skipped.
WORLD_FEEDS = [
    ("https://feeds.a.dj.com/rss/RSSWorldNews.xml",                 "WSJ"),
    ("https://feeds.bbci.co.uk/news/world/rss.xml",                 "BBC"),
    ("https://rss.nytimes.com/services/xml/rss/nyt/World.xml",      "NYT"),
    ("https://www.theguardian.com/world/rss",                       "Guardian"),
]

MARKETS_FEEDS = [
    ("https://feeds.a.dj.com/rss/RSSMarketsMain.xml",               "WSJ"),
    ("http://feeds.marketwatch.com/marketwatch/topstories/",        "MarketWatch"),
    ("https://www.cnbc.com/id/20910258/device/rss/rss.html",        "CNBC"),
    ("https://www.federalreserve.gov/feeds/press_all.xml",          "Fed"),
]

# arXiv categories that map to "applied/computational math you can use":
#   ML / LLMs / generative -> cs.LG, cs.CL, stat.ML
#   control & systems      -> math.OC, eess.SY
#   numerical / comp math  -> math.NA
#   quant finance          -> q-fin.*
ARXIV_CATS = [
    "cs.LG", "cs.CL", "stat.ML",
    "math.OC", "eess.SY", "math.NA",
    "q-fin.CP", "q-fin.MF", "q-fin.PM", "q-fin.TR", "q-fin.ST", "q-fin.RM",
]
ARXIV_API = (
    "http://export.arxiv.org/api/query?search_query="
    + "+OR+".join(f"cat:{c}" for c in ARXIV_CATS)
    + "&sortBy=submittedDate&sortOrder=descending&max_results=40"
)

# Optional AI ranking of the research pool (approximates alphaXiv-style relevance).
# If an API key is present as an env var / GitHub secret, the job ranks a pool of
# recent papers by relevance to these interests; otherwise it falls back to newest.
RESEARCH_POOL = 40            # how many recent papers to consider before ranking
INTEREST_DESCRIPTION = (
    "A quant researcher in applied/computational math. Most relevant: large language "
    "models (efficiency, inference, long-context), generative models (diffusion, flow "
    "matching), convex/stochastic/large-scale optimization, optimal and stochastic "
    "control, reinforcement learning, numerical methods, and quantitative finance that "
    "is actually usable (deep hedging, volatility modeling/calibration, portfolio "
    "optimization, market microstructure, execution, statistical arbitrage, asset pricing)."
)
ANTHROPIC_MODEL = "claude-haiku-4-5-20251001"   # cheap; edit if you prefer another
OPENAI_MODEL = "gpt-4o-mini"

socket.setdefaulttimeout(25)


# ----------------------------------------------------------------------------
# Fetching
# ----------------------------------------------------------------------------
def _clean(text, limit):
    text = " ".join((text or "").split())
    if len(text) > limit:
        text = text[: limit - 1].rstrip(" ,.;:—-") + "…"
    return text


def fetch_news(feeds, limit, char_limit):
    """Pull recent entries across feeds, newest first, de-duplicated by title."""
    collected = []
    for url, label in feeds:
        try:
            parsed = feedparser.parse(url)
        except Exception:
            continue
        for e in parsed.entries[:12]:
            title = _clean(getattr(e, "title", ""), char_limit)
            if not title:
                continue
            ts = getattr(e, "published_parsed", None) or getattr(e, "updated_parsed", None)
            ts = datetime.datetime(*ts[:6]) if ts else datetime.datetime.min
            collected.append({"title": title, "meta": label.upper(), "ts": ts})

    collected.sort(key=lambda x: x["ts"], reverse=True)
    out, seen = [], set()
    for item in collected:
        key = item["title"].lower()[:40]
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
        if len(out) >= limit:
            break
    return out


def fetch_research_pool(char_limit):
    """Recent papers across the configured arXiv categories (newest first)."""
    try:
        parsed = feedparser.parse(ARXIV_API)
    except Exception:
        return []
    pool, seen = [], set()
    for e in parsed.entries:
        title = _clean(getattr(e, "title", ""), char_limit)
        if not title:
            continue
        key = title.lower()[:40]
        if key in seen:
            continue
        seen.add(key)
        cat = ""
        prim = getattr(e, "arxiv_primary_category", None)
        if isinstance(prim, dict):
            cat = prim.get("term", "")
        if not cat and getattr(e, "tags", None):
            cat = e.tags[0].get("term", "")
        meta = f"ARXIV · {cat.upper()}" if cat else "ARXIV"
        pool.append({"title": title, "meta": meta})
        if len(pool) >= RESEARCH_POOL:
            break
    return pool


def _ai_rank(titles, n):
    """Return indices of the n most relevant titles, or None if no API key / failure."""
    prompt = (
        "You curate a daily research digest for this reader:\n"
        f"{INTEREST_DESCRIPTION}\n\nCandidate papers:\n"
        + "\n".join(f"{i}: {t}" for i, t in enumerate(titles))
        + f"\n\nReturn ONLY a JSON array of the {n} most relevant and substantive "
          "paper indices, most relevant first. Example: [3, 0, 7]"
    )
    try:
        key = os.environ.get("ANTHROPIC_API_KEY")
        if key:
            body = json.dumps({
                "model": ANTHROPIC_MODEL, "max_tokens": 60,
                "messages": [{"role": "user", "content": prompt}],
            }).encode()
            req = urllib.request.Request(
                "https://api.anthropic.com/v1/messages", data=body,
                headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                         "content-type": "application/json"})
            data = json.loads(urllib.request.urlopen(req, timeout=30).read())
            text = data["content"][0]["text"]
        else:
            key = os.environ.get("OPENAI_API_KEY")
            if not key:
                return None
            body = json.dumps({
                "model": OPENAI_MODEL, "max_tokens": 60,
                "messages": [{"role": "user", "content": prompt}],
            }).encode()
            req = urllib.request.Request(
                "https://api.openai.com/v1/chat/completions", data=body,
                headers={"authorization": f"Bearer {key}",
                         "content-type": "application/json"})
            data = json.loads(urllib.request.urlopen(req, timeout=30).read())
            text = data["choices"][0]["message"]["content"]

        start, end = text.find("["), text.rfind("]")
        idx = json.loads(text[start:end + 1])
        return [i for i in idx if isinstance(i, int)]
    except Exception:
        return None


def select_research(limit, char_limit):
    pool = fetch_research_pool(char_limit)
    if not pool:
        return []
    ranked = _ai_rank([p["title"] for p in pool], limit)
    if ranked:
        picked = [pool[i] for i in ranked if 0 <= i < len(pool)][:limit]
        if picked:
            return picked
    return pool[:limit]   # fallback: newest


# ----------------------------------------------------------------------------
# Sample data (offline --selftest)
# ----------------------------------------------------------------------------
SAMPLE = {
    "World": [
        {"title": "Ceasefire talks resume as both sides signal cautious openness", "meta": "REUTERS"},
        {"title": "Record flooding displaces thousands across the river delta", "meta": "BBC"},
    ],
    "Research": [
        {"title": "Adaptive step-size methods for stochastic convex optimization", "meta": "ARXIV · MATH.OC"},
        {"title": "A diffusion prior for calibrating implied volatility surfaces", "meta": "ARXIV · Q-FIN.CP"},
        {"title": "Low-rank attention reduces inference cost in long-context LLMs", "meta": "ARXIV · CS.LG"},
    ],
    "Markets": [
        {"title": "Futures edge higher ahead of inflation print as yields slip", "meta": "WSJ"},
        {"title": "Oil steadies after a volatile week; gold holds near a record", "meta": "MARKETWATCH"},
        {"title": "Fed minutes point to a slower path on rate cuts", "meta": "FED"},
    ],
}


# ----------------------------------------------------------------------------
# HTML build
# ----------------------------------------------------------------------------
TEMPLATE = """<!DOCTYPE html><html><head><meta charset="utf-8">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Newsreader:opsz,wght@6..72,400;6..72,500;6..72,600&family=IBM+Plex+Mono:wght@400;500&family=Inter:wght@600;800&display=swap" rel="stylesheet">
<style>
  :root{
    --ink:#f4f1ea; --muted:#8f8c84; --accent:#c9a24b;
    --hair:rgba(255,255,255,0.10);
    --serif:"Newsreader",Georgia,serif;
    --mono:"IBM Plex Mono",ui-monospace,monospace;
    --sans:"Inter",-apple-system,sans-serif;
  }
  *{margin:0;padding:0;box-sizing:border-box;}
  html,body{width:__W__px;height:__H__px;}
  body{
    background:linear-gradient(180deg,#0c0c0f 0%,#121116 __CLOCKPCT__%,#17130d 100%);
    color:var(--ink);font-family:var(--sans);overflow:hidden;
    -webkit-font-smoothing:antialiased;
  }
  .clockzone{height:__CLOCKPX__px;}
  .feed{
    height:calc(__H__px - __CLOCKPX__px);
    padding:0 84px 150px;overflow:hidden;
  }
  .masthead{
    display:flex;align-items:baseline;justify-content:space-between;
    padding-bottom:26px;border-bottom:1.5px solid var(--hair);margin-bottom:6px;
  }
  .masthead .date{font-family:var(--serif);font-weight:600;font-size:46px;color:var(--ink);}
  .masthead .upd{font-family:var(--mono);font-size:24px;letter-spacing:1px;color:var(--muted);}
  .eyebrow{
    font-family:var(--sans);font-weight:800;font-size:27px;letter-spacing:8px;
    text-transform:uppercase;color:var(--accent);margin:40px 0 6px;
  }
  .item{display:flex;gap:26px;padding:22px 0;border-top:1.5px solid var(--hair);}
  .item:first-of-type{border-top:none;}
  .bar{flex:0 0 5px;width:5px;border-radius:3px;background:var(--accent);opacity:.85;}
  .hl{font-family:var(--serif);font-weight:500;font-size:47px;line-height:1.16;color:var(--ink);}
  .meta{font-family:var(--mono);font-weight:500;font-size:23px;letter-spacing:2px;color:var(--muted);margin-top:11px;}
</style></head>
<body>
  <div class="clockzone"></div>
  <div class="feed">
    <div class="masthead"><span class="date">__DATE__</span><span class="upd">__UPD__</span></div>
__SECTIONS__
  </div>
</body></html>"""


def build_html(sections, now):
    blocks = []
    for name, items in sections:
        rows = [f'<div class="eyebrow">{html.escape(name)}</div>']
        if not items:
            rows.append('<div class="item"><div class="bar"></div><div>'
                        '<div class="hl">No items available right now.</div></div></div>')
        for it in items:
            rows.append(
                '<div class="item"><div class="bar"></div><div>'
                f'<div class="hl">{html.escape(it["title"])}</div>'
                f'<div class="meta">{html.escape(it["meta"])}</div>'
                '</div></div>'
            )
        blocks.append("\n".join(rows))

    date_str = now.strftime("%A, %B %-d")
    upd_str = "UPDATED " + now.strftime("%-I:%M %p").upper()
    return (TEMPLATE
            .replace("__W__", str(WIDTH))
            .replace("__H__", str(HEIGHT))
            .replace("__CLOCKPX__", str(int(HEIGHT * CLOCK_ZONE)))
            .replace("__CLOCKPCT__", str(int(CLOCK_ZONE * 100)))
            .replace("__DATE__", html.escape(date_str))
            .replace("__UPD__", html.escape(upd_str))
            .replace("__SECTIONS__", "\n".join(blocks)))


# ----------------------------------------------------------------------------
# Render
# ----------------------------------------------------------------------------
def render_png(html_str, out):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": WIDTH, "height": HEIGHT},
                                device_scale_factor=1)
        page.set_content(html_str, wait_until="networkidle")
        try:
            page.evaluate("document.fonts.ready")
        except Exception:
            pass
        page.wait_for_timeout(500)
        page.screenshot(path=out, clip={"x": 0, "y": 0, "width": WIDTH, "height": HEIGHT})
        browser.close()


def main():
    selftest = "--selftest" in sys.argv
    now = datetime.datetime.now(ZoneInfo(TIMEZONE))

    if selftest:
        sections = [(k, SAMPLE[k][: ITEMS[k]]) for k in ("World", "Research", "Markets")]
    else:
        sections = [
            ("World",    fetch_news(WORLD_FEEDS,   ITEMS["World"],   MAX_CHARS["World"])),
            ("Research", select_research(           ITEMS["Research"], MAX_CHARS["Research"])),
            ("Markets",  fetch_news(MARKETS_FEEDS, ITEMS["Markets"], MAX_CHARS["Markets"])),
        ]

    html_str = build_html(sections, now)
    with open("headlines.html", "w") as f:
        f.write(html_str)
    print("Wrote headlines.html")

    if "--html-only" in sys.argv:
        return
    render_png(html_str, OUTPUT)
    print(f"Wrote {OUTPUT}")


if __name__ == "__main__":
    main()
