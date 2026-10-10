# Morning Brief

A personal morning briefing that arrives as a roughly 10 minute voice note. It opens with real market numbers, sized against a normal day, then the news I want to hear about. Claude writes the script, ElevenLabs reads it aloud, and the MP3 and transcript are emailed to you. I listen to it on the way to work.

**Listen to a sample:** [`sample/morning_brief_2026-10-10.mp3`](sample/) (transcript alongside it).

## What's in a briefing

It opens with "Morning Hugh. Here's your market news." and goes straight in.

**Markets** (`markets.py`): the US and Swiss 10-year yields, SOFR, €STR, the Dow, S&P 500, Nasdaq, MSCI World, MSCI Emerging Markets, Euro Stoxx 50, gold spot and EUR/USD. Prices are given in percent, yields and rates in basis points. Each move is compared with the standard deviation of that asset's daily moves over the past year:

- under 1 standard deviation: one quick line
- 1 to 1.5: a sentence
- over 1.5: a notable move, and Claude searches the web for why it happened

**Central banks and data:** the next Fed and ECB decision dates, what fed funds futures price for the next two Fed meetings, what money markets price for the ECB, and any recent US or euro area inflation, GDP, payrolls or unemployment releases.

**News**, in order: markets and business, US, Europe and the EU, Ireland (in more detail), AI and software (including notable open-source releases), and a short world round-up. Edit the `SECTIONS` list in the script to make it your own.

**Sources:** market data from CNBC, the New York Fed, the ECB Data Portal and fed funds futures via Yahoo Finance; releases from the BLS and BEA; news from CNBC, the FT, BBC, NPR, Politico Europe, Euronews, RTÉ, The Irish Times, the Irish Independent, TechCrunch, The Verge, Ars Technica, MIT Technology Review and Hacker News. All free, with no keys needed.

## How the script gets written

- **With an Anthropic API key**, Claude (Opus 5.5) writes the script like a sharp colleague talking you through the morning: direct, natural, with a line on why each story matters. It uses web search to explain big moves, check ECB pricing and fill in AI news, and only uses facts from the notes or its searches.
- **Without one**, a simple template reads the numbers and headlines out. It works, but it doesn't flow.

## Cost

Roughly 30 to 40 cents a run with ElevenLabs, plus some cents for Claude and its web searches if you use it. Resend's free tier covers the email.

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
