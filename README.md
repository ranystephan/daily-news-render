# Daily headline lock-screen wallpaper

Generates a small **album** of newspaper-style pages every morning, sized for the
iPhone 17 Pro Max (1320 × 2868):

- `headlines.png` — the front page: **World**, **Research** (arXiv: ML / control /
  optimization / numerical / quant finance), and **Markets**.
- `card-01.png … card-NN.png` — one full single-story page per item (headline, deck,
  body text). Research cards carry a takeaway + the paper's abstract.
- `manifest.json` — the ordered list of today's images, read by the iOS Shortcut.

A GitHub Action renders and commits these daily. On the phone, an iOS Shortcut refreshes
a Photos album from the manifest each morning, and a **Photo Shuffle** lock screen sourced
from that album lets you tap through the day's stories.

---

## Part A — GitHub (one-time, ~10 min)

1. **Create a new repository** and make it **Public** (so your phone can fetch the image
   with no login). The image contains only public headlines, nothing private.

2. **Add these four files** to the repo, keeping the folder layout:
   ```
   render.py
   requirements.txt
   .github/workflows/daily.yml
   README.md
   ```
   (Easiest: on github.com use **Add file → Upload files**, drag them in, commit.
   The workflow file must stay at `.github/workflows/daily.yml`.)

3. **Allow the Action to commit:** repo **Settings → Actions → General →
   Workflow permissions → Read and write permissions → Save.**

4. **Generate the first image:** open the **Actions** tab → *Daily headline wallpaper* →
   **Run workflow**. After ~1–2 min a `headlines.png` appears in the repo. Open it to check.

5. **Your base URL** (stable, never changes — the phone reads the manifest from here):
   ```
   https://raw.githubusercontent.com/<YOUR-USERNAME>/<YOUR-REPO>/main/
   ```
   The manifest lives at `…/main/manifest.json`; each image is `…/main/<name>` from its
   `images` list (e.g. `…/main/headlines.png`, `…/main/card-01.png`).

### Adjust to taste (all near the top of `render.py`)
- `TIMEZONE` — set to your zone, e.g. `"America/New_York"`, so the date/time stamp is right.
- `ITEMS` — headlines per section, e.g. `{"World": 2, "Research": 3, "Markets": 3}`.
- `ARXIV_CATS` — add/remove arXiv categories for the Research section.
- `WORLD_FEEDS` / `MARKETS_FEEDS` — swap in any RSS feeds you prefer.
- Cron time is in **`.github/workflows/daily.yml`** and is **UTC**. `0 13 * * *` ≈ 6 AM PT.

### Research ranking — newest vs. AI-relevance (optional)
By default the Research section shows the **newest** papers across your arXiv categories —
free, no key, fully robust. To instead have it **rank a pool of recent papers by relevance
to your interests** (reproducing alphaXiv-style picks, unattended), add an API key:

1. Get an API key from Anthropic (console.anthropic.com) **or** OpenAI (platform.openai.com).
   This is pay-per-use and separate from a Claude Pro / ChatGPT Plus plan; this job uses a
   few hundred tokens a day — roughly cents per month.
2. In the repo: **Settings → Secrets and variables → Actions → New repository secret.**
   Name it `ANTHROPIC_API_KEY` (or `OPENAI_API_KEY`) and paste the key.
3. Add it to the render step in `.github/workflows/daily.yml`:
   ```yaml
      - name: Render wallpaper
        run: python render.py
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
   ```
   (or `OPENAI_API_KEY`). With no key set, it silently uses newest-first — nothing breaks.

Edit `INTEREST_DESCRIPTION` in `render.py` to steer what "relevant" means.

---

## Part B — iPhone album that rotates daily

The phone keeps a Photos album in sync with the manifest each morning, and a **Photo
Shuffle** lock screen sourced from that album lets you tap through the day's stories.

**1. Create the album**
- **Photos → Albums → +  → New Album** → name it **Daily Brief**. Leave it empty.

**2. Build the refresh shortcut**
- **Shortcuts → +** → name it **Daily Brief Refresh**. Add these actions in order:
  1. **Text** → `https://raw.githubusercontent.com/<YOUR-USERNAME>/<YOUR-REPO>/main/`
     (your base URL from A5). Tap the field, this is your `BASE`.
  2. **Find Photos** → Album **is** Daily Brief. (Clears yesterday.)
  3. **Delete Photos** → input = Photos from step 2. *(Run once manually to grant the
     “delete” permission; afterward it’s silent.)*
  4. **Get Contents of URL** → `BASE` + `manifest.json`.
  5. **Get Dictionary Value** → Get **Value** for **images** in (Contents of URL).
  6. **Repeat with Each** (item = the images list):
     - **Text** → `BASE` + **Repeat Item**.
     - **Get Contents of URL** → that Text.
     - **Save to Photo Album** → album **Daily Brief**.
  7. (end Repeat)

**3. Automate it daily**
- **Shortcuts → Automation → +  → Create Personal Automation.**
- **Time of Day** → e.g. **7:00 AM** → **Daily** → Next. (After the GitHub cron — cron is
  6 AM PT, so 7 AM is safe.)
- **Run Shortcut** → **Daily Brief Refresh** → Next.
- **Ask Before Running OFF** → confirm **Don't Ask** → Done.

**4. Set the wallpaper (one-time)**
- Run the shortcut once so the album has today's images.
- **Settings → Wallpaper → Add New Wallpaper → Photo Shuffle.**
- **Use Album** → **Daily Brief**. Set **Shuffle Frequency → On Tap**. Save → set as the pair.

> **Order:** Photo Shuffle picks from the album at random, not in manifest order — so the
> front page isn't guaranteed first; tapping cycles the day's set. iOS has no native
> ordered, tap-to-advance wallpaper.

---

## Test it now
Run **Daily Brief Refresh** once (▶). Check the **Daily Brief** album fills with today's
pages, then tap the lock screen to cycle them. If the album doesn't appear under
**Use Album**, make sure it has at least one photo (run the shortcut first), then re-pick it.

## Good to know
- **Public repos get unlimited free Actions minutes.** This job uses ~1–2 min/day.
- GitHub **pauses scheduled workflows after 60 days of no commits** to a repo; it emails
  you, and any small commit re-enables it. (The daily commit normally keeps it alive.)
- The image is served via a CDN that may cache for a few minutes — harmless for a daily file.
- You don't need your paid news subscriptions for this; headlines come from public RSS feeds.

## Preview the design locally (optional)
```
pip install -r requirements.txt
python -m playwright install chromium
python render.py --selftest      # renders headlines.png from sample data, no network
```
