# Daily headline lock-screen wallpaper

Generates a wallpaper PNG every morning with three sections — **World**, **Research**
(newest arXiv papers in ML / control / optimization / numerical / quant finance), and
**Markets** — sized for the iPhone 17 Pro Max (1320 × 2868). A GitHub Action renders and
commits the image daily; an iOS Shortcut downloads it and sets your lock screen.

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

5. **Your image URL** (this is what the phone uses — stable, never changes):
   ```
   https://raw.githubusercontent.com/<YOUR-USERNAME>/<YOUR-REPO>/main/headlines.png
   ```

### Adjust to taste (all near the top of `render.py`)
- `TIMEZONE` — set to your zone, e.g. `"America/New_York"`, so the date/time stamp is right.
- `ITEMS` — headlines per section, e.g. `{"World": 2, "Research": 3, "Markets": 3}`.
- `ARXIV_CATS` — add/remove arXiv categories for the Research section.
- `WORLD_FEEDS` / `MARKETS_FEEDS` — swap in any RSS feeds you prefer.
- Cron time is in **`.github/workflows/daily.yml`** and is **UTC**. `0 10 * * *` ≈ 6 AM ET.

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

## Part B — iPhone Shortcut (one-time, ~3 min)

**1. Build the shortcut**
- Open **Shortcuts → +** (new shortcut). Name it **Headline Wallpaper**.
- Add action **Get Contents of URL**. Paste your image URL from step A5. Leave method **GET**.
- Add action **Set Wallpaper**:
  - Set the image to the **Contents of URL** output.
  - Tap to expand options → turn **Show Preview OFF**.
  - Choose **Lock Screen** (and Home Screen too if you want).

**2. Automate it daily**
- Go to the **Automation** tab → **+** → **Create Personal Automation**.
- Trigger **Time of Day** → e.g. **7:00 AM** → **Daily** → Next.
- Action **Run Shortcut** → pick **Headline Wallpaper** → Next.
- Turn **Ask Before Running OFF** → confirm **Don't Ask** → Done.

Schedule the phone time a bit **after** the GitHub cron so the fresh image is ready
(e.g. cron 6 AM ET → phone 7 AM).

---

## Test it now
On your phone, open the Shortcut and tap the **▶ play** button once. Your lock screen
should update. If it doesn't, set your current lock screen to a **Photo** wallpaper first
(not a Photo Shuffle / collection), then try again.

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
