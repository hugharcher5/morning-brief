# Morning Brief

A personal news briefing that arrives as a voice note every morning. It gathers the day's headlines and market moves, turns them into a spoken-style script, reads it aloud with an ElevenLabs voice, and emails the MP3 with the transcript attached. I listened to it on the way to work.

## What's in a briefing

- **US markets:** how the S&P 500, Nasdaq, Dow, gold, EUR/USD and GBP/USD are moving, described in words rather than numbers, since numbers are hard to follow by ear.
- **What's driving them:** top stories from MarketWatch and CNBC.
- **Geopolitics and politics:** BBC World and BBC Politics.
- **The Fed and interest rates:** the Federal Reserve's own press releases and CNBC Economy.
- **EU, UK and Dublin:** BBC Business, RTE Business and RTE News.
- **Earnings:** the biggest companies reporting that day.
- **Asia:** the Nikkei and Hang Seng, plus CNBC Asia.

Every source is a free RSS feed or a free public quote endpoint, so the only costs are the voice generation and the email. A run cost about 30 cents. The feed is fully customisable: change the sources in `RSS_SOURCES` and the sections in `build_transcript()`.

## How it runs

A GitHub Actions workflow (`.github/workflows/briefing.yml`) runs the script every morning at 06:00 UTC. You can also run it by hand from the **Actions** tab with **Run workflow**.

## Set it up yourself

1. Fork or copy this repo.
2. Add three secrets under **Settings → Secrets and variables → Actions**:
   - `ELEVENLABS_API_KEY`: from your ElevenLabs account.
   - `RESEND_API_KEY`: from your Resend account.
   - `TO_EMAIL`: the address the briefing should go to.
3. Optionally change `VOICE_ID` in the script to any ElevenLabs voice you like.
4. Run it once from the Actions tab to test.

## Stack

Python, feedparser, the ElevenLabs text-to-speech API, Resend for email, and GitHub Actions for scheduling.
