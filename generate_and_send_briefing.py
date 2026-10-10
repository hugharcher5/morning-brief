#!/usr/bin/env python3
"""
Morning Brief: a personal news briefing delivered as a voice note.

1. Gathers market data (yields, overnight rates, indices, gold, EUR/USD, what's
   priced for the Fed) with each move sized in standard deviations against the
   past year (see markets.py), plus the day's headlines from free RSS feeds.
2. Turns them into a spoken script. With ANTHROPIC_API_KEY set, Claude writes
   it and searches the web for the reason behind any notable move; without it,
   a simple template reads the numbers and headlines out.
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

import markets

TODAY = datetime.date.today()

# --- Settings you may want to change ---------------------------------------
FROM_EMAIL = "onboarding@resend.dev"   # Resend's test sender; use your own verified domain later
VOICE_ID = os.environ.get("ELEVENLABS_VOICE_ID", "onwK4e9ZLuTAKqWW03F9")  # ElevenLabs "Daniel, Steady Broadcaster"
ELEVENLABS_MODEL = os.environ.get("ELEVENLABS_MODEL", "eleven_v4")
CLAUDE_MODEL = "claude-opus-5-5"
ITEMS_PER_SOURCE = 5
TARGET_WORDS = "1,500 to 1,700"   # about 10 minutes read aloud
# ---------------------------------------------------------------------------

# Each section: a heading for the script, then its feeds. Edit freely to make
# the briefing your own; the order here is the order it's read in.
SECTIONS = [
    ("Markets and business", [
        ("CNBC Markets", "https://www.cnbc.com/id/15839069/device/rss/rss.html"),
        ("FT Markets", "https://www.ft.com/markets?format=rss"),
        ("CNBC Finance", "https://www.cnbc.com/id/10000664/device/rss/rss.html"),
        ("CNBC Top News", "https://www.cnbc.com/id/100003114/device/rss/rss.html"),
    ]),
    ("The economy and interest rates", [
        ("CNBC Economy", "https://www.cnbc.com/id/20910258/device/rss/rss.html"),
        ("Federal Reserve", "https://www.federalreserve.gov/feeds/press_all.xml"),
    ]),
    ("US news", [
        ("BBC US and Canada", "http://feeds.bbci.co.uk/news/world/us_and_canada/rss.xml"),
        ("NPR", "https://feeds.npr.org/1001/rss.xml"),
    ]),
    ("Europe and the EU", [
        ("Politico Europe", "https://www.politico.eu/feed/"),
        ("Euronews", "https://www.euronews.com/rss?level=theme&name=news"),
        ("BBC Europe", "http://feeds.bbci.co.uk/news/world/europe/rss.xml"),
        ("BBC Business", "http://feeds.bbci.co.uk/news/business/rss.xml"),
    ]),
    ("Ireland", [
        ("RTE News", "https://www.rte.ie/news/rss/news-headlines.xml"),
        ("RTE Business", "https://www.rte.ie/news/rss/business-headlines.xml"),
        ("Irish Times", "https://www.irishtimes.com/arc/outboundfeeds/feed-irish-news/?outputType=xml"),
        ("Irish Times Business", "https://www.irishtimes.com/arc/outboundfeeds/feed-business/?outputType=xml"),
        ("Irish Independent", "https://www.independent.ie/irish-news/rss"),
    ]),
    ("AI and software", [
        ("TechCrunch AI", "https://techcrunch.com/category/artificial-intelligence/feed/"),
        ("The Verge AI", "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml"),
        ("Ars Technica AI", "https://arstechnica.com/ai/feed/"),
        ("MIT Technology Review", "https://www.technologyreview.com/feed/"),
        ("Hacker News best", "https://hnrss.org/best"),   # where new open-source tools surface first
    ]),
    ("World", [
        ("BBC World", "http://feeds.bbci.co.uk/news/world/rss.xml"),
    ]),
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
    return {"date": f"{TODAY:%A, %B} {TODAY.day}",
            "markets": markets.gather_markets(TODAY), "sections": sections}


def notes_as_text(notes):
    lines = [f"Date: {notes['date']}", "", markets.markets_as_text(notes["markets"])]
    for heading, stories in notes["sections"]:
        lines += ["", f"## {heading}"]
        lines += [f"- {s['title']} ({s['source']}): {s['summary']}" for s in stories] or ["- nothing new"]
    return "\n".join(lines)


def template_script(notes):
    """Fallback script with no AI: reads headlines out in order."""
    parts = ["Morning Hugh. Here's your market news."]
    assets = notes["markets"]["assets"]
    if assets:
        parts.append(". ".join(markets.spoken_move(a) for a in assets) + ".")
    for heading, stories in notes["sections"]:
        if stories:
            body = " ".join(f"{s['title']}. {s['summary']}".strip() for s in stories)
            parts.append(f"{heading}. {body}")
    parts.append("That's your briefing for this morning. Have a good day.")
    return "\n\n".join(parts)


SYSTEM_PROMPT = """\
You write Hugh's morning briefing. It is read aloud by a text-to-speech voice on his commute, and \
he works in finance, so it should sound like a sharp colleague on a trading desk talking him \
through the morning: human, warm, natural rhythm, but direct. No scene-setting, no "grab a \
coffee", no filler. Open with exactly "Morning Hugh. Here's your market news." and go straight \
into the numbers.

Markets come first, and they use real numbers: percentage moves for prices, basis points for \
yields and overnight rates. Each move in the notes has a size in sigma (standard deviations of \
the past year's daily moves):
- quiet (under 1 sigma): one short clause, grouped with others, e.g. "Gold up a tenth of a \
percent, euro-dollar flat."
- normal (1 to 1.5 sigma): one sentence.
- NOTABLE (1.5 sigma or more): say it's a big move for that asset, and explain why it happened. \
Use web search to find the cause; don't guess.
Then the central banks: the date of the next Fed and ECB decisions and what the market is \
pricing for each. Fed pricing is in the notes. For the ECB, search for what €STR futures or \
money markets currently price for the next meeting. Then any US or euro area inflation, GDP, \
payrolls or unemployment numbers released in the last day or two (check the notes, and search \
for euro area releases), with the figure against expectations when you can find it.

Then the news, in this order, each with real substance rather than a headline list:
- Market and business news: deals, earnings, credit, anything moving sectors.
- US news, then Europe and the EU: politics and policy with economic weight first.
- Ireland: Hugh is in Dublin, so go into more detail here; the economy, housing, the Budget, \
industrial relations, big Irish companies and the main home news.
- AI and software: model releases, big funding or deals, regulation, and any genuinely \
breakthrough software or open-source release (the kind of thing that changes how people \
work, like AI decompiling or reverse-engineering software). Search for the biggest AI and \
open-source developments of the last day or two if the notes look thin.
- World: a short round-up of anything major.
Skip trivial, lifestyle or repeated stories. Give each story that matters a line on why it \
matters.

Rules: never invent a figure, quote or event; anything not in the notes must come from your \
searches. Write numbers the way they're said aloud ("four point two percent", "eleven basis \
points", "fifty-one thousand six hundred"). Round index levels sensibly. Output only the spoken \
script, after you have finished searching: no headings, lists, markdown, citations or stage \
directions. Separate topics with blank lines. End with one short sign-off line."""


def claude_script(notes):
    """Have Claude write the script, searching the web for the reasons behind big moves."""
    import anthropic

    client = anthropic.Anthropic()
    messages = [{"role": "user", "content": (
        f"Today's notes. Aim for about {TARGET_WORDS} words in total.\n\n" + notes_as_text(notes))}]
    for _ in range(5):   # resume if a long search turn pauses
        response = client.beta.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=16000,
            output_config={"effort": "medium"},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            system=SYSTEM_PROMPT,
            tools=[{"type": "web_search_20260209", "name": "web_search", "max_uses": 8}],
            messages=messages,
        )
        if response.stop_reason != "pause_turn":
            break
        messages.append({"role": "assistant", "content": response.content})
    if response.stop_reason == "refusal":
        raise RuntimeError("Claude declined to write the script")
    # The script is the text after the last search result
    blocks = list(response.content)
    last_search = max((i for i, b in enumerate(blocks) if b.type.endswith("_tool_result")), default=-1)
    text = "".join(b.text for b in blocks[last_search + 1:] if b.type == "text").strip()
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


def strip_id3(mp3):
    """Drop the ID3 tag at the start of a later MP3 part so joined parts play without a glitch."""
    if mp3[:3] == b"ID3" and len(mp3) > 10:
        size = (mp3[6] << 21) | (mp3[7] << 14) | (mp3[8] << 7) | mp3[9]
        return mp3[10 + size:]
    return mp3


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
        audio += resp.content if i == 0 else strip_id3(resp.content)
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
