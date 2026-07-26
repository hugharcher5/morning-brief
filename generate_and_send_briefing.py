#!/usr/bin/env python3
"""
Daily Morning Briefing -> ElevenLabs voice + Resend email.

Runs on GitHub Actions (see .github/workflows/daily-briefing.yml).
Gathers free public headlines, writes a spoken-style transcript, converts
it to an mp3 using ElevenLabs, then emails the mp3 + transcript via Resend.

Required secrets (set as GitHub repo secrets, Settings -> Secrets and
variables -> Actions):
    ELEVENLABS_API_KEY
    RESEND_API_KEY

Edit TO_EMAIL / FROM_EMAIL / VOICE_ID below before first use.
"""

import os
import sys
import base64
import datetime
import feedparser
import requests

TODAY = datetime.date.today()
IS_WEEKEND = TODAY.weekday() >= 5

ELEVENLABS_API_KEY = os.environ["ELEVENLABS_API_KEY"]
RESEND_API_KEY = os.environ["RESEND_API_KEY"]

# --- EDIT THESE THREE LINES ---
TO_EMAIL = "archerh2005@gmail.com"
FROM_EMAIL = "onboarding@resend.dev"
VOICE_ID = "21m00Tcm4TlvDq8ikWAM"  # ElevenLabs default "Rachel" voice.
# Browse voices at elevenlabs.io -> Voice Library, click one, copy its
# Voice ID from the "..." menu, and paste it here to change the voice.
# -------------------------------

RSS_SOURCES = {
    "New York Post": "https://nypost.com/feed/",
    "BBC World": "http://feeds.bbci.co.uk/news/world/rss.xml",
    "BBC Business": "http://feeds.bbci.co.uk/news/business/rss.xml",
    "NYT Front Page": "https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml",
    "NYT Business": "https://rss.nytimes.com/services/xml/rss/nyt/Business.xml",
    "WSJ World News": "https://feeds.a.dj.com/rss/RSSWorldNews.xml",
    "WSJ Markets": "https://feeds.a.dj.com/rss/RSSMarketsMain.xml",
    "Financial Times": "https://www.ft.com/rss/home",
    "RTE News": "https://www.rte.ie/news/rss/news-headlines.xml",
    "TheJournal.ie": "https://www.thejournal.ie/feed/",
    "Politico": "https://www.politico.com/rss/politics-news.xml",
    "Axios": "https://api.axios.com/feed/",
}


def fetch_rss(name, url, max_items=2):
    try:
        feed = feedparser.parse(url, request_headers={"User-Agent": "Mozilla/5.0"})
        if feed.bozo and not feed.entries:
            raise ValueError(feed.bozo_exception)
        items = []
        for entry in feed.entries[:max_items]:
            title = entry.get("title", "(no title)")
            summary = (entry.get("summary", "") or entry.get("description", ""))[:300]
            items.append({"title": title, "summary": summary})
        return items
    except Exception as e:
        print(f"  [skip] {name}: {e}", file=sys.stderr)
        return []


def summarize(items):
    if not items:
        return None
    parts = []
    for it in items:
        line = it["title"]
        if it["summary"]:
            line += f" -- {it['summary']}"
        parts.append(line)
    return " ".join(parts)


def build_transcript():
    """Assemble a flowing, spoken-style script from today's headlines.
    Template-based (no extra LLM API needed) -- edit the phrasing below
    freely to change the "voice" of the writing."""

    lines = [f"Good morning. Here's your reading briefing for {TODAY.strftime('%A, %B %d')}.", ""]
    lines.append("Starting with the US desk.")

    nyp = summarize(fetch_rss("New York Post", RSS_SOURCES["New York Post"]))
    if nyp:
        lines.append(f"From the New York Post: {nyp}")

    nyt = summarize(fetch_rss("NYT Front Page", RSS_SOURCES["NYT Front Page"], 2) +
                     fetch_rss("NYT Business", RSS_SOURCES["NYT Business"], 2))
    if nyt:
        lines.append(f"The New York Times is covering: {nyt}")

    wsj = summarize(fetch_rss("WSJ World News", RSS_SOURCES["WSJ World News"], 2) +
                     fetch_rss("WSJ Markets", RSS_SOURCES["WSJ Markets"], 2))
    if wsj:
        lines.append(f"On markets, the Wall Street Journal reports: {wsj}")

    ft = summarize(fetch_rss("Financial Times", RSS_SOURCES["Financial Times"]))
    if ft:
        lines.append(f"The Financial Times adds this on the international and markets side: {ft}")

    if IS_WEEKEND:
        bbc = summarize(fetch_rss("BBC World", RSS_SOURCES["BBC World"]))
        if bbc:
            lines.append(f"Since it's the weekend, here's the broader world roundup from the BBC: {bbc}")
    else:
        pol = summarize(fetch_rss("Politico", RSS_SOURCES["Politico"]))
        if pol:
            lines.append(f"In politics, Politico is reporting: {pol}")
        axios = summarize(fetch_rss("Axios", RSS_SOURCES["Axios"]))
        if axios:
            lines.append(f"And Axios flags: {axios}")

    lines.append("")
    lines.append("Now to the Dublin and EU desk.")

    rte = summarize(fetch_rss("RTE News", RSS_SOURCES["RTE News"]))
    if rte:
        lines.append(f"RTE News is leading with: {rte}")

    tj = summarize(fetch_rss("TheJournal.ie", RSS_SOURCES["TheJournal.ie"]))
    if tj:
        lines.append(f"TheJournal.ie adds: {tj}")

    ftEurope = summarize(fetch_rss("Financial Times", RSS_SOURCES["Financial Times"], 2))
    if ftEurope:
        lines.append(f"On the European economic side, the Financial Times covers: {ftEurope}")

    lines.append("")
    lines.append("That's the briefing for this morning. Full text access to the Irish "
                  "Times, FT, WSJ, and Business Post remains available separately via "
                  "your UCD Library subscriptions if you want to read the original "
                  "coverage on any of today's stories.")

    return "\n\n".join(lines)


def text_to_speech(text):
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE_ID}"
    headers = {
        "xi-api-key": ELEVENLABS_API_KEY,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg",
    }
    payload = {
        "text": text,
        "model_id": "eleven_flash_v2",
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=120)
    resp.raise_for_status()
    return resp.content  # raw mp3 bytes


def send_email(transcript, audio_bytes):
    url = "https://api.resend.com/emails"
    headers = {
        "Authorization": f"Bearer {RESEND_API_KEY}",
        "Content-Type": "application/json",
    }
    audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")
    payload = {
        "from": FROM_EMAIL,
        "to": [TO_EMAIL],
        "subject": f"Morning Reading Briefing (audio) — {TODAY.strftime('%A, %B %d, %Y')}",
        "text": transcript,
        "attachments": [
            {
                "filename": f"morning_briefing_{TODAY.isoformat()}.mp3",
                "content": audio_b64,
            }
        ],
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=60)
    resp.raise_for_status()
    print("Email sent:", resp.json())


if __name__ == "__main__":
    transcript = build_transcript()
    print("----- TRANSCRIPT -----")
    print(transcript)
    print("----- GENERATING AUDIO -----")
    audio = text_to_speech(transcript)
    print(f"Got {len(audio)} bytes of audio.")
    send_email(transcript, audio)
