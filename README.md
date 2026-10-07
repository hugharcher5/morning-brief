# Morning Brief

A personal news briefing that arrives as a 10 to 15 minute voice note every morning. It gathers the day's headlines and market moves, turns them into a natural spoken script, reads it aloud with an ElevenLabs voice, and emails you the MP3 and the transcript. I listened to it on the way to work.

**Listen to a sample:** [`sample/morning_brief_2026-10-07.mp3`](sample/) (transcript alongside it).

## What's in a briefing

The briefing follows the order of the `SECTIONS` list in the script, which you can edit to make it your own:

- **Markets:** the S&P 500, Nasdaq, Dow, gold, oil, EUR/USD, GBP/USD, the Nikkei and the Hang Seng, described in words rather than numbers, since numbers are hard to follow by ear. Plus the day's biggest earnings reports and market stories.
- **The economy and interest rates:** CNBC Economy and the Federal Reserve's own announcements (routine notices are filtered out).
- **AI and technology:** TechCrunch AI and The Verge AI.
- **US news:** BBC US and Canada, and NPR.
- **World and geopolitics:** BBC World.
- **Europe and the UK:** BBC Europe, Business and Politics.
- **Ireland:** RTÉ News and RTÉ Business.
- **Asia:** CNBC Asia.

Every source is a free RSS feed or a free public market endpoint. Stories repeated across feeds are removed automatically.

## How the script gets written

- **With an Anthropic API key**, Claude (Opus 5.5) writes the script like a radio presenter: smooth transitions, a line of context on why each story matters, and only facts from the day's feeds.
- **Without one**, a simple template reads the headlines out section by section. It works, but it doesn't flow.

## Cost

Roughly 30 cents a run with ElevenLabs, plus a few cents for Claude if you use it. Resend's free tier covers the email.

## Set it up yourself

You need your **own** accounts and keys. GitHub never copies secrets when a repo is forked, so your copy can't use anyone else's keys or credits.

1. Fork or copy this repo.
2. Add secrets under **Settings → Secrets and variables → Actions**:
   - `ELEVENLABS_API_KEY` (required): from your ElevenLabs account.
   - `RESEND_API_KEY` and `TO_EMAIL` (optional): to have the briefing emailed to you.
   - `ANTHROPIC_API_KEY` (optional, recommended): for the natural-sounding script.
   - `ELEVENLABS_VOICE_ID` (optional): any ElevenLabs voice you like.
3. Go to **Actions → Daily Morning Briefing → Run workflow** to test it.
4. To get it every morning at 06:00 UTC, uncomment the two `schedule` lines in `.github/workflows/briefing.yml`. It's manual-only by default, so nothing runs or costs anything until you choose.

## Run it on your own computer

```bash
pip install -r requirements.txt
python generate_and_send_briefing.py --dry-run            # print today's script, no paid calls
python generate_and_send_briefing.py --out brief.mp3 --no-email
python generate_and_send_briefing.py --script my_script.txt   # voice a script you wrote yourself
```

Set the same environment variables as above (for example in your shell) before a real run.

## Stack

Python, feedparser, the Anthropic API, the ElevenLabs text-to-speech API, Resend for email, and GitHub Actions for scheduling. Long scripts are split at sentence boundaries and voiced in parts, with neighbouring text passed along so the delivery stays smooth across the joins.
