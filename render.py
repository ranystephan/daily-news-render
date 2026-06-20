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
import re
import sys
import glob
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
CLOCK_ZONE = 0.20                    # top fraction left empty for the iOS clock
OUTPUT = "headlines.png"
NAMEPLATE = "The Daily Brief"        # masthead title at the top of the page

# How many items to show per section (tune to taste / fit).
ITEMS = {"World": 2, "Research": 3, "Markets": 3}

# Max characters per headline before it's trimmed (research titles run long).
MAX_CHARS = {"World": 92, "Research": 92, "Markets": 92}

# Max characters for a Research takeaway line (the italic "deck" under the title).
NOTE_CHARS = 150

# Max characters of body text shown on a per-story "card" image.
BODY_CHARS = 540

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


def _strip_html(s):
    """Remove tags/entities from an RSS summary, collapse whitespace."""
    s = re.sub(r"<[^>]+>", " ", s or "")
    return " ".join(html.unescape(s).split())


def fetch_news(feeds, limit, char_limit):
    """Pull recent entries across feeds, newest first, de-duplicated by title."""
    collected = []
    for url, label in feeds:
        try:
            parsed = feedparser.parse(url)
        except Exception:
            continue
        for e in parsed.entries[:12]:
            full = " ".join((getattr(e, "title", "") or "").split())
            title = _clean(full, char_limit)
            if not title:
                continue
            ts = getattr(e, "published_parsed", None) or getattr(e, "updated_parsed", None)
            ts = datetime.datetime(*ts[:6]) if ts else datetime.datetime.min
            body = _strip_html(getattr(e, "summary", "") or getattr(e, "description", ""))
            collected.append({"title": title, "full": full, "meta": label.upper(),
                              "ts": ts, "body": body})

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
        full = " ".join((getattr(e, "title", "") or "").split())
        title = _clean(full, char_limit)
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
        abstract = " ".join((getattr(e, "summary", "") or "").split())
        pool.append({"title": title, "full": full, "meta": meta, "abstract": abstract})
        if len(pool) >= RESEARCH_POOL:
            break
    return pool


def _first_sentences(text, limit):
    """A short, clean takeaway from an abstract: 1-2 sentences, capped at `limit`."""
    text = " ".join((text or "").split())
    if not text:
        return ""
    out = ""
    for part in re.split(r"(?<=[.!?])\s+", text):
        if not out:
            out = part
        elif len(out) + 1 + len(part) <= limit:
            out += " " + part
        else:
            break
        if out.endswith((".", "!", "?")) and len(out) >= limit * 0.55:
            break
    if len(out) > limit:
        out = out[: limit - 1].rstrip(" ,.;:—-") + "…"
    return out


def _chat(prompt, max_tokens):
    """One LLM call via Anthropic or OpenAI; returns the text, or None if no key/failure."""
    try:
        key = os.environ.get("ANTHROPIC_API_KEY")
        if key:
            body = json.dumps({
                "model": ANTHROPIC_MODEL, "max_tokens": max_tokens,
                "messages": [{"role": "user", "content": prompt}],
            }).encode()
            req = urllib.request.Request(
                "https://api.anthropic.com/v1/messages", data=body,
                headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                         "content-type": "application/json"})
            data = json.loads(urllib.request.urlopen(req, timeout=40).read())
            return data["content"][0]["text"]
        key = os.environ.get("OPENAI_API_KEY")
        if not key:
            return None
        body = json.dumps({
            "model": OPENAI_MODEL, "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }).encode()
        req = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions", data=body,
            headers={"authorization": f"Bearer {key}", "content-type": "application/json"})
        data = json.loads(urllib.request.urlopen(req, timeout=40).read())
        return data["choices"][0]["message"]["content"]
    except Exception:
        return None


def _ai_rank(titles, n):
    """Return indices of the n most relevant titles, or None if no API key / failure."""
    prompt = (
        "You curate a daily research digest for this reader:\n"
        f"{INTEREST_DESCRIPTION}\n\nCandidate papers:\n"
        + "\n".join(f"{i}: {t}" for i, t in enumerate(titles))
        + f"\n\nReturn ONLY a JSON array of the {n} most relevant and substantive "
          "paper indices, most relevant first. Example: [3, 0, 7]"
    )
    text = _chat(prompt, 60)
    if not text:
        return None
    try:
        start, end = text.find("["), text.rfind("]")
        idx = json.loads(text[start:end + 1])
        return [i for i in idx if isinstance(i, int)]
    except Exception:
        return None


def _ai_takeaways(items):
    """One crisp takeaway per paper (title+abstract), or None if no API key / failure."""
    prompt = (
        "For each paper below write ONE sharp sentence (max 20 words) stating its key "
        "result or why it matters, for a quant / applied-math reader. Be concrete — name "
        "the method or finding. No fluff, do not start with 'This paper' or 'The authors'.\n\n"
        + "\n\n".join(f"{i}. {it['title']}\nAbstract: {it.get('abstract', '')[:700]}"
                      for i, it in enumerate(items))
        + "\n\nReturn ONLY a JSON array of strings, one per paper, in the same order."
    )
    text = _chat(prompt, 400)
    if not text:
        return None
    try:
        start, end = text.find("["), text.rfind("]")
        arr = json.loads(text[start:end + 1])
        return [s for s in arr if isinstance(s, str)]
    except Exception:
        return None


def select_research(limit, char_limit):
    pool = fetch_research_pool(char_limit)
    if not pool:
        return []
    ranked = _ai_rank([p["title"] for p in pool], limit)
    if ranked:
        picked = [pool[i] for i in ranked if 0 <= i < len(pool)][:limit] or pool[:limit]
    else:
        picked = pool[:limit]   # fallback: newest

    notes = _ai_takeaways(picked)   # None without an API key
    for i, it in enumerate(picked):
        note = notes[i] if notes and i < len(notes) else None
        note = _clean(note, NOTE_CHARS) if note else _first_sentences(it.get("abstract", ""), NOTE_CHARS)
        it["note"] = note
    return picked


# ----------------------------------------------------------------------------
# Sample data (offline --selftest)
# ----------------------------------------------------------------------------
SAMPLE = {
    "World": [
        {"title": "Ceasefire talks resume as both sides signal cautious openness", "meta": "REUTERS",
         "body": "Negotiators returned to the table after a week-long pause, with mediators describing the mood as "
                 "guardedly constructive. Both delegations agreed to a narrow agenda focused on prisoner exchanges "
                 "and humanitarian corridors before any discussion of a wider political settlement."},
        {"title": "Record flooding displaces thousands across the river delta", "meta": "BBC",
         "body": "Relentless monsoon rains pushed the river past its highest recorded level, submerging low-lying "
                 "districts and forcing mass evacuations. Officials warned that crop losses could deepen food prices "
                 "for months as relief teams struggle to reach cut-off villages."},
    ],
    "Research": [
        {"title": "Adaptive step-size methods for stochastic convex optimization", "meta": "ARXIV · MATH.OC",
         "note": "A line-search-free schedule that matches hand-tuned learning rates and removes the main knob practitioners dread.",
         "abstract": "We propose an adaptive step-size rule for stochastic convex optimization that requires no "
                     "line search and no prior knowledge of the smoothness constant. The method matches the "
                     "convergence rate of optimally-tuned SGD across a range of problems while eliminating the "
                     "learning-rate hyperparameter, and we provide high-probability guarantees under heavy-tailed noise."},
        {"title": "A diffusion prior for calibrating implied volatility surfaces", "meta": "ARXIV · Q-FIN.CP",
         "note": "Learns an arbitrage-free vol surface from sparse quotes, beating SVI on out-of-sample repricing.",
         "abstract": "We train a diffusion model as a prior over implied volatility surfaces and use it to calibrate "
                     "to sparse, noisy option quotes. The resulting surfaces are static-arbitrage-free by construction "
                     "and reprice held-out strikes more accurately than SVI and SSVI baselines, especially in the wings."},
        {"title": "Low-rank attention reduces inference cost in long-context LLMs", "meta": "ARXIV · CS.LG",
         "note": "Cuts attention FLOPs ~3x at 128k context with under 1% quality loss, no retraining needed.",
         "abstract": "We show that attention matrices in long-context transformers are approximately low-rank and "
                     "introduce a training-free factorization that cuts attention FLOPs by roughly three times at a "
                     "128k context window. Across reasoning and retrieval benchmarks the quality drop stays under one percent."},
    ],
    "Markets": [
        {"title": "Futures edge higher ahead of inflation print as yields slip", "meta": "WSJ",
         "body": "Stock-index futures pointed to a firmer open as Treasury yields eased and traders positioned for a "
                 "key inflation reading. A softer print would bolster the case for rate cuts later this year, though "
                 "strategists cautioned that a hot number could quickly reverse the move."},
        {"title": "Oil steadies after a volatile week; gold holds near a record", "meta": "MARKETWATCH",
         "body": "Crude prices stabilized after sharp swings driven by supply worries and shifting demand forecasts, "
                 "while gold hovered just below its all-time high as investors sought a hedge against policy "
                 "uncertainty and a softer dollar."},
        {"title": "Fed minutes point to a slower path on rate cuts", "meta": "FED",
         "body": "Minutes from the latest policy meeting showed officials in no hurry to ease, citing sticky services "
                 "inflation and resilient labor data. Several participants favored holding rates steady until they saw "
                 "clearer evidence that price pressures were durably returning to target."},
    ],
}


# ----------------------------------------------------------------------------
# HTML build
# ----------------------------------------------------------------------------
TEMPLATE = """<!DOCTYPE html><html><head><meta charset="utf-8">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Newsreader:ital,opsz,wght@0,6..72,400;0,6..72,500;0,6..72,600;0,6..72,700;1,6..72,400;1,6..72,500&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
  :root{
    --paper:#f6f3ea; --ink:#181511; --soft:#4b443a; --muted:#8a8073;
    --rule:rgba(24,21,17,0.24); --hair:rgba(24,21,17,0.13);
    --serif:"Newsreader",Georgia,"Times New Roman",serif;
    --mono:"IBM Plex Mono",ui-monospace,monospace;
  }
  *{margin:0;padding:0;box-sizing:border-box;}
  html,body{width:__W__px;height:__H__px;}
  body{
    background:var(--paper);
    color:var(--ink);font-family:var(--serif);overflow:hidden;
    -webkit-font-smoothing:antialiased;
  }
  .clockzone{height:__CLOCKPX__px;}
  .feed{
    height:calc(__H__px - __CLOCKPX__px);
    padding:0 86px 150px;overflow:hidden;
  }
  .nameplate{
    text-align:center;font-weight:700;font-size:104px;line-height:.96;
    letter-spacing:-1.5px;padding-bottom:22px;
  }
  .dateline{
    text-align:center;font-family:var(--mono);font-size:22px;letter-spacing:3px;
    text-transform:uppercase;color:var(--soft);padding:13px 0;
    border-top:2.5px solid var(--ink);border-bottom:1px solid var(--ink);
  }
  .section{margin-top:42px;}
  .section-head{
    text-align:center;font-weight:700;font-size:29px;letter-spacing:7px;
    text-transform:uppercase;color:var(--ink);
    padding-bottom:13px;margin-bottom:4px;border-bottom:1.5px solid var(--rule);
  }
  .item{padding:23px 0;border-top:1px solid var(--hair);}
  .item:first-of-type{border-top:none;}
  .hl{font-weight:600;font-size:49px;line-height:1.17;color:var(--ink);letter-spacing:-0.3px;}
  .note{font-style:italic;font-weight:400;font-size:35px;line-height:1.34;color:var(--soft);margin-top:11px;}
  .meta{font-family:var(--mono);font-weight:500;font-size:21px;letter-spacing:2px;
        text-transform:uppercase;color:var(--muted);margin-top:13px;}
</style></head>
<body>
  <div class="clockzone"></div>
  <div class="feed">
    <div class="nameplate">__NAME__</div>
    <div class="dateline">__DATE__ &nbsp;·&nbsp; __UPD__</div>
__SECTIONS__
  </div>
</body></html>"""


def build_html(sections, now):
    blocks = []
    for name, items in sections:
        rows = [f'<div class="section"><div class="section-head">{html.escape(name)}</div>']
        if not items:
            rows.append('<div class="item"><div class="hl">No items available right now.</div></div>')
        for it in items:
            note = it.get("note")
            note_html = f'<div class="note">{html.escape(note)}</div>' if note else ""
            rows.append(
                '<div class="item">'
                f'<div class="hl">{html.escape(it["title"])}</div>'
                f'{note_html}'
                f'<div class="meta">{html.escape(it["meta"])}</div>'
                '</div>'
            )
        rows.append('</div>')
        blocks.append("\n".join(rows))

    date_str = now.strftime("%A, %B %-d").upper()
    upd_str = "UPDATED " + now.strftime("%-I:%M %p").upper()
    return (TEMPLATE
            .replace("__W__", str(WIDTH))
            .replace("__H__", str(HEIGHT))
            .replace("__CLOCKPX__", str(int(HEIGHT * CLOCK_ZONE)))
            .replace("__NAME__", html.escape(NAMEPLATE))
            .replace("__DATE__", html.escape(date_str))
            .replace("__UPD__", html.escape(upd_str))
            .replace("__SECTIONS__", "\n".join(blocks)))


# A single-story "card" — one per item, for the rotating album.
DETAIL_TEMPLATE = """<!DOCTYPE html><html><head><meta charset="utf-8">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Newsreader:ital,opsz,wght@0,6..72,400;0,6..72,500;0,6..72,600;0,6..72,700;1,6..72,400;1,6..72,500&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
  :root{
    --paper:#f6f3ea; --ink:#181511; --soft:#4b443a; --muted:#8a8073;
    --rule:rgba(24,21,17,0.24); --hair:rgba(24,21,17,0.13);
    --serif:"Newsreader",Georgia,"Times New Roman",serif;
    --mono:"IBM Plex Mono",ui-monospace,monospace;
  }
  *{margin:0;padding:0;box-sizing:border-box;}
  html,body{width:__W__px;height:__H__px;}
  body{background:var(--paper);color:var(--ink);font-family:var(--serif);
       overflow:hidden;-webkit-font-smoothing:antialiased;}
  .clockzone{height:__CLOCKPX__px;}
  .story{height:calc(__H__px - __CLOCKPX__px);padding:0 86px 150px;overflow:hidden;}
  .kicker{font-family:var(--mono);font-weight:500;font-size:24px;letter-spacing:5px;
          text-transform:uppercase;color:var(--ink);
          padding-bottom:16px;border-bottom:2.5px solid var(--ink);margin-bottom:30px;}
  .story-hl{font-weight:700;font-size:78px;line-height:1.08;letter-spacing:-1px;color:var(--ink);}
  .story-deck{font-style:italic;font-weight:400;font-size:42px;line-height:1.3;
              color:var(--soft);margin-top:24px;}
  .story-rule{height:1.5px;background:var(--rule);margin:38px 0;}
  .story-body{font-weight:400;font-size:39px;line-height:1.46;color:var(--ink);}
  .story-foot{font-family:var(--mono);font-weight:500;font-size:22px;letter-spacing:2px;
              text-transform:uppercase;color:var(--muted);
              margin-top:40px;padding-top:20px;border-top:1px solid var(--hair);}
</style></head>
<body>
  <div class="clockzone"></div>
  <div class="story">
    <div class="kicker">__KICKER__</div>
    <h1 class="story-hl">__TITLE__</h1>
    __DECK__
    <div class="story-rule"></div>
    __BODY__
    <div class="story-foot">__FOOT__</div>
  </div>
</body></html>"""


def build_detail_html(section, it, now):
    deck = it.get("note") or ""
    body = _strip_html(it.get("body") or it.get("abstract") or "")
    if len(body) > BODY_CHARS:
        body = body[: BODY_CHARS - 1].rstrip(" ,.;:—-") + "…"
    deck_html = f'<div class="story-deck">{html.escape(deck)}</div>' if deck else ""
    body_html = f'<div class="story-body">{html.escape(body)}</div>' if body else ""
    foot = f'{it.get("meta", "")} · {now.strftime("%A, %B %-d").upper()}'
    return (DETAIL_TEMPLATE
            .replace("__W__", str(WIDTH))
            .replace("__H__", str(HEIGHT))
            .replace("__CLOCKPX__", str(int(HEIGHT * CLOCK_ZONE)))
            .replace("__KICKER__", html.escape(section.upper()))
            .replace("__TITLE__", html.escape(it.get("full") or it["title"]))
            .replace("__DECK__", deck_html)
            .replace("__BODY__", body_html)
            .replace("__FOOT__", html.escape(foot)))


# ----------------------------------------------------------------------------
# Render
# ----------------------------------------------------------------------------
def render_pages(jobs):
    """jobs: list of (html_str, out_path). One shared browser renders every page."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox"])
        for html_str, out in jobs:
            page = browser.new_page(viewport={"width": WIDTH, "height": HEIGHT},
                                    device_scale_factor=1)
            page.set_content(html_str, wait_until="networkidle")
            try:
                page.evaluate("document.fonts.ready")
            except Exception:
                pass
            page.wait_for_timeout(400)
            page.screenshot(path=out, clip={"x": 0, "y": 0, "width": WIDTH, "height": HEIGHT})
            page.close()
        browser.close()


def main():
    selftest = "--selftest" in sys.argv
    now = datetime.datetime.now(ZoneInfo(TIMEZONE))

    if selftest:
        sections = [(k, [dict(x) for x in SAMPLE[k][: ITEMS[k]]])
                    for k in ("World", "Research", "Markets")]
    else:
        sections = [
            ("World",    fetch_news(WORLD_FEEDS,   ITEMS["World"],   MAX_CHARS["World"])),
            ("Research", select_research(           ITEMS["Research"], MAX_CHARS["Research"])),
            ("Markets",  fetch_news(MARKETS_FEEDS, ITEMS["Markets"], MAX_CHARS["Markets"])),
        ]

    # Drop yesterday's cards so the album never accumulates stale stories.
    for f in glob.glob("card-*.png"):
        os.remove(f)

    # Page 1: the overview. Pages 2..N: one story card per item, in reading order.
    jobs = [(build_html(sections, now), OUTPUT)]
    manifest = [OUTPUT]
    for name, items in sections:
        for it in items:
            out = f"card-{len(manifest):02d}.png"
            jobs.append((build_detail_html(name, it, now), out))
            manifest.append(out)

    with open("headlines.html", "w") as f:
        f.write(jobs[0][0])

    if "--html-only" in sys.argv:
        return

    render_pages(jobs)
    with open("manifest.json", "w") as f:
        json.dump({"date": now.strftime("%Y-%m-%d"), "images": manifest}, f, indent=2)
    print(f"Wrote {len(jobs)} images + manifest.json")


if __name__ == "__main__":
    main()
