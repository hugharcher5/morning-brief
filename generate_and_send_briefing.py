#!/usr/bin/env python3
"""
Morning Brief: a personal news briefing delivered as a voice note.

1. Gathers the day's headlines from free RSS feeds and market moves from
   Yahoo Finance's free chart endpoint.
2. Turns them into a spoken script. With ANTHROPIC_API_KEY set, Claude writes
   a natural, flowing 10 to 15 minute script; without it, a simple template
   reads the headlines out section by section.
3. Reads the script aloud with ElevenLabs and saves an MP3.
4. Emails the MP3 and transcript with Resend, if RESEND_API_KEY and TO_EMAIL
   are set.

Environment variables (GitHub: Settings -> Secrets and variables -> Actions):
    ELEVENLABS_API_KEY   required for audio
    RESEND_API_KEY       optional, needed to email the briefing
    TO_EMAIL             optional, where to email it
    ANTHROPIC_API_KEY    optional, makes the script flow naturally
    ELEVENLABS_VOICE_ID  optional, defaults to VOICE_ID below
    ELEVENLABS_MODEL     optional, defaults to ELEVENLABS_MODEL below

Usage:
    python generate_and_send_briefing.py                 # full run
    python generate_and_send_briefing.py --dry-run       # print the script only, no API calls
    python generate_and_send_briefing.py --script my.txt # voice a script you wrote yourself
    python generate_and_send_briefing.py --out brief.mp3 --no-email
"""

import argparse
import base64
import datetime
import html
import os
import re
import sys

import feedparser
import requests

TODAY = datetime.date.today()

# --- Settings you may want to change ---------------------------------------
FROM_EMAIL = "onboarding@resend.dev"   # Resend's test sender; use your own verified domain later
VOICE_ID = os.environ.get("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")  # ElevenLabs "Rachel"
ELEVENLABS_MODEL = os.environ.get("ELEVENLABS_MODEL", "eleven_multilingual_v2")
CLAUDE_MODEL = "claude-opus-5-5"
ITEMS_PER_SOURCE = 4
TARGET_WORDS = "1,600 to 2,000"   # roughly 10 to 15 minutes read aloud
# ---------------------------------------------------------------------------

# Each section: a heading for the script, then its feeds. Edit freely to make
# the briefing your own; the order here is the order it's read in.
SECTIONS = [
    ("Markets", [
        ("CNBC Top News", "https://www.cnbc.com/id/100003114/device/rss/rss.html"),
        ("MarketWatch", "http://feeds.marketwatch.com/marketwatch/topstories/"),
    ]),
    ("The economy and interest rates", [
        ("CNBC Economy", "https://www.cnbc.com/id/20910258/device/rss/rss.html"),
        ("Federal Reserve", "https://www.federalreserve.gov/feeds/press_all.xml"),
    ]),
    ("AI and technology", [
        ("TechCrunch AI", "https://techcrunch.com/category/artificial-intelligence/feed/"),
        ("The Verge AI", "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml"),
    ]),
    ("US news", [
        ("BBC US and Canada", "http://feeds.bbci.co.uk/news/world/us_and_canada/rss.xml"),
        ("NPR", "https://feeds.npr.org/1001/rss.xml"),
    ]),
    ("World and geopolitics", [
        ("BBC World", "http://feeds.bbci.co.uk/news/world/rss.xml"),
    ]),
    ("Europe and the UK", [
        ("BBC Europe", "http://feeds.bbci.co.uk/news/world/europe/rss.xml"),
        ("BBC Business", "http://feeds.bbci.co.uk/news/business/rss.xml"),
        ("BBC Politics", "http://feeds.bbci.co.uk/news/politics/rss.xml"),
    ]),
    ("Ireland", [
        ("RTE News", "https://www.rte.ie/news/rss/news-headlines.xml"),
        ("RTE Business", "https://www.rte.ie/news/rss/business-headlines.xml"),
    ]),
    ("Asia", [
        ("CNBC Asia", "https://www.cnbc.com/id/19832390/device/rss/rss.html"),
    ]),
]

MARKETS = [
    ("The S&P 500", "^GSPC"), ("The Nasdaq", "^IXIC"), ("The Dow", "^DJI"),
    ("Gold", "GC=F"), ("Oil", "CL=F"),
    ("The euro against the dollar", "EURUSD=X"), ("The pound against the dollar", "GBPUSD=X"),
    ("Japan's Nikkei", "^N225"), ("Hong Kong's Hang Seng", "^HSI"),
]

# Routine notices that make dull listening
SKIP_TITLES = re.compile(
    r"approval of application|announces approval|enforcement action|termination of enforcement"
    r"|minutes of the board|agenda|discount rate", re.I)

UA = {"User-Agent": "Mozilla/5.0 (morning-brief; +https://github.com/hugharcher5/morning-brief)"}


def clean(text):
    """Strip HTML tags and entities from feed text and tidy the whitespace."""
    text = html.unescape(re.sub(r"<[^>]+>", " ", text or ""))
    return re.sub(r"\s+", " ", text).strip()


def fetch_feed(name, url):
    try:
        feed = feedparser.parse(url, request_headers=UA)
        if feed.bozo and not feed.entries:
            raise ValueError(feed.bozo_exception)
    except Exception as e:  # one broken feed shouldn't stop the briefing
        print(f"  [skip] {name}: {e}", file=sys.stderr)
        return []
    stories = []
    for entry in feed.entries:
        title = clean(entry.get("title"))
        if not title or SKIP_TITLES.search(title):
            continue
        summary = clean(entry.get("summary") or entry.get("description"))
        if summary.lower().startswith(title.lower()):
            summary = summary[len(title):].strip(" -:")
        stories.append({"source": name, "title": title, "summary": summary[:300]})
        if len(stories) >= ITEMS_PER_SOURCE:
            break
    return stories


def fetch_move(name, symbol):
    """Describe a market move in words; numbers are hard to follow by ear."""
    try:
        resp = requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
                            headers=UA, timeout=10)
        resp.raise_for_status()
        meta = resp.json()["chart"]["result"][0]["meta"]
        price, prev = meta.get("regularMarketPrice"), meta.get("chartPreviousClose") or meta.get("previousClose")
        if price is None or not prev:
            return None
    except Exception as e:
        print(f"  [skip] quote {symbol}: {e}", file=sys.stderr)
        return None
    pct = (price - prev) / prev * 100
    if abs(pct) < 0.15:
        return f"{name} is little changed"
    size = "slightly" if abs(pct) < 0.5 else "solidly" if abs(pct) < 1.5 else "sharply" if abs(pct) < 3 else "dramatically"
    return f"{name} is {size} {'higher' if pct > 0 else 'lower'}"


def fetch_earnings():
    """Biggest companies reporting today, from Nasdaq's public calendar (best effort)."""
    try:
        resp = requests.get(f"https://api.nasdaq.com/api/calendar/earnings?date={TODAY.isoformat()}",
                            headers={**UA, "Accept": "application/json"}, timeout=10)
        resp.raise_for_status()
        rows = ((resp.json().get("data") or {}).get("rows")) or []
    except Exception as e:
        print(f"  [skip] earnings: {e}", file=sys.stderr)
        return []

    def cap(row):
        try:
            return float((row.get("marketCap") or "0").replace("$", "").replace(",", ""))
        except ValueError:
            return 0.0

    names = [re.sub(r"[,.]?\s*(Inc|Ltd|Corp|Corporation|Co|plc)\.?$", "", (r.get("name") or r.get("symbol") or "").strip())
             for r in sorted(rows, key=cap, reverse=True)[:5]]
    return [n for n in names if n]


def gather():
    """Collect everything the script needs, removing stories repeated across feeds."""
    seen, sections = set(), []
    for heading, feeds in SECTIONS:
        stories = []
        for name, url in feeds:
            for s in fetch_feed(name, url):
                key = re.sub(r"[^a-z0-9]", "", s["title"].lower())[:60]
                if key not in seen:
                    seen.add(key)
                    stories.append(s)
        sections.append((heading, stories))
    moves = [m for m in (fetch_move(n, s) for n, s in MARKETS) if m]
    return {"date": f"{TODAY:%A, %B} {TODAY.day}",
            "moves": moves, "earnings": fetch_earnings(), "sections": sections}


def notes_as_text(notes):
    lines = [f"Date: {notes['date']}", "", "Market moves: " + "; ".join(notes["moves"])]
    if notes["earnings"]:
        lines.append("Reporting earnings today: " + ", ".join(notes["earnings"]))
    for heading, stories in notes["sections"]:
        lines += ["", f"## {heading}"]
        lines += [f"- {s['title']} ({s['source']}): {s['summary']}" for s in stories] or ["- nothing new"]
    return "\n".join(lines)


def template_script(notes):
    """Fallback script with no AI: reads headlines out in order."""
    parts = [f"Good morning. Here's your briefing for {notes['date']}."]
    if notes["moves"]:
        parts.append("First, the markets. " + ". ".join(notes["moves"]) + ".")
    if notes["earnings"]:
        parts.append("Reporting earnings today: " + ", ".join(notes["earnings"]) + ".")
    for heading, stories in notes["sections"]:
        if stories:
            body = " ".join(f"{s['title']}. {s['summary']}".strip() for s in stories)
            parts.append(f"{heading}. {body}")
    parts.append("That's your briefing for this morning. Have a good day.")
    return "\n\n".join(parts)


def claude_script(notes):
    """Have Claude turn the notes into a natural spoken script."""
    import anthropic

    system = (
        "You write a personal morning news briefing that is read aloud by a text-to-speech voice "
        "while the listener commutes to work. Write it the way a good radio presenter speaks: warm, "
        "plain and conversational, with smooth transitions between stories and a short line of "
        "context on why each one matters. Use only facts in the notes; never invent figures, quotes "
        "or events. Describe market moves in words, not numbers. Write numbers, currencies and "
        "abbreviations the way they should be said aloud. Output plain spoken text only: no "
        "headings, bullet points, markdown, emoji or stage directions. Separate topics with blank lines."
    )
    prompt = (
        f"Here are today's notes. Write a briefing of about {TARGET_WORDS} words, roughly 10 to 15 "
        "minutes aloud. Follow the section order in the notes, skip anything trivial or repetitive, "
        "open with a one-line greeting and the date, and close with a brief sign-off.\n\n"
        + notes_as_text(notes)
    )
    client = anthropic.Anthropic()
    response = client.beta.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=16000,
        output_config={"effort": "medium"},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    if response.stop_reason == "refusal":
        raise RuntimeError("Claude declined to write the script")
    text = "".join(b.text for b in response.content if b.type == "text").strip()
    if not text:
        raise RuntimeError(f"Claude returned no script (stop_reason={response.stop_reason})")
    return text


def chunks(text, limit=4000):
    """Split the script at paragraph or sentence boundaries into TTS-sized pieces."""
    pieces, current = [], ""
    for para in re.split(r"\n\s*\n", text):
        sentences = re.split(r"(?<=[.!?])\s+", para.strip()) if len(para) > limit else [para.strip()]
        for s in sentences:
            if current and len(current) + len(s) + 2 > limit:
                pieces.append(current)
                current = ""
            current = f"{current}\n\n{s}".strip() if current else s
    if current:
        pieces.append(current)
    return pieces


def text_to_speech(text):
    """Voice the script with ElevenLabs, chunk by chunk, keeping the delivery continuous."""
    key = os.environ.get("ELEVENLABS_API_KEY")
    if not key:
        sys.exit("ELEVENLABS_API_KEY is not set. Add your own key to make the audio.")
    parts = chunks(text)
    audio = b""
    for i, part in enumerate(parts):
        payload = {
            "text": part,
            "model_id": ELEVENLABS_MODEL,
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
            # Context from either side keeps intonation smooth across the joins
            "previous_text": parts[i - 1][-500:] if i else None,
            "next_text": parts[i + 1][:500] if i + 1 < len(parts) else None,
        }
        resp = requests.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE_ID}?output_format=mp3_44100_128",
            headers={"xi-api-key": key, "Content-Type": "application/json", "Accept": "audio/mpeg"},
            json={k: v for k, v in payload.items() if v is not None},
            timeout=300,
        )
        if resp.status_code != 200:
            sys.exit(f"ElevenLabs error {resp.status_code}: {resp.text[:300]}")
        audio += resp.content
        print(f"  voiced part {i + 1} of {len(parts)}")
    return audio


def send_email(script, audio):
    key, to = os.environ.get("RESEND_API_KEY"), os.environ.get("TO_EMAIL")
    if not (key and to):
        print("RESEND_API_KEY or TO_EMAIL not set, so skipping the email.")
        return
    resp = requests.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={
            "from": FROM_EMAIL,
            "to": [to],
            "subject": f"Morning Brief: {TODAY.strftime('%A, %B %d, %Y')}",
            "text": script,
            "attachments": [{"filename": f"morning_brief_{TODAY.isoformat()}.mp3",
                             "content": base64.b64encode(audio).decode()}],
        },
        timeout=60,
    )
    if resp.status_code >= 300:
        sys.exit(f"Resend error {resp.status_code}: {resp.text[:300]}")
    print("Email sent.")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="print the script and stop (no paid API calls)")
    parser.add_argument("--script", help="voice this text file instead of generating a script")
    parser.add_argument("--out", default=f"morning_brief_{TODAY.isoformat()}.mp3", help="where to save the MP3")
    parser.add_argument("--no-email", action="store_true", help="save the MP3 but don't email it")
    args = parser.parse_args()

    if args.script:
        script = open(args.script, encoding="utf-8").read().strip()
    else:
        notes = gather()
        if os.environ.get("ANTHROPIC_API_KEY") and not args.dry_run:
            script = claude_script(notes)
        else:
            script = template_script(notes)

    print("----- SCRIPT -----\n" + script + "\n------------------")
    print(f"{len(script.split())} words, about {len(script.split()) / 150:.0f} minutes aloud")
    if args.dry_run:
        return

    audio = text_to_speech(script)
    with open(args.out, "wb") as f:
        f.write(audio)
    print(f"Saved {args.out} ({len(audio) // 1024} KB)")
    if not args.no_email:
        send_email(script, audio)


if __name__ == "__main__":
    main()
