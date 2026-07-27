#!/usr/bin/env python3
"""
Daily Morning Briefing -> ElevenLabs voice + Resend email.
Finance/markets-focused version.

Runs on GitHub Actions (see .github/workflows/briefing.yml).
Gathers free public headlines + free market quotes, writes a spoken-style
transcript, converts it to an mp3 using ElevenLabs, then emails the mp3 +
transcript via Resend.

Required secrets (GitHub repo Settings -> Secrets and variables -> Actions):
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
# -------------------------------

MAX_ITEMS_PER_SOURCE = 2

# ---------------------------------------------------------------------------
# Free RSS sources, reorganized around markets/economy/policy/geopolitics.
# ---------------------------------------------------------------------------
RSS_SOURCES = {
    "CNBC Top News": "https://www.cnbc.com/id/100003114/device/rss/rss.html",
    "CNBC Economy": "https://www.cnbc.com/id/20910258/device/rss/rss.html",
    "MarketWatch Top Stories": "http://feeds.marketwatch.com/marketwatch/topstories/",
    "Fed Press Releases": "https://www.federalreserve.gov/feeds/press_all.xml",
    "BBC World": "http://feeds.bbci.co.uk/news/world/rss.xml",
    "BBC Politics": "http://feeds.bbci.co.uk/news/politics/rss.xml",
    "BBC Business": "http://feeds.bbci.co.uk/news/business/rss.xml",
    "RTE Business": "https://www.rte.ie/news/rss/business-headlines.xml",
    "RTE News": "https://www.rte.ie/news/rss/news-headlines.xml",
    "CNBC Asia Markets": "https://www.cnbc.com/id/19832390/device/rss/rss.html",
}

# ---------------------------------------------------------------------------
# Free market quotes via Yahoo Finance's public chart endpoint (no API key).
# ---------------------------------------------------------------------------
TICKERS = {
    "S&P 500": "^GSPC",
    "Nasdaq": "^IXIC",
    "Dow Jones": "^DJI",
    "Gold": "GC=F",
    "Euro/Dollar": "EURUSD=X",
    "Pound/Dollar": "GBPUSD=X",
}

ASIA_TICKERS = {
    "Nikkei 225 (Japan)": "^N225",
    "Hang Seng (Hong Kong)": "^HSI",
}


def fetch_rss(name, url, max_items=MAX_ITEMS_PER_SOURCE):
    try:
        feed = feedparser.parse(url, request_headers={"User-Agent": "Mozilla/5.0"})
        if feed.bozo and not feed.entries:
            raise ValueError(feed.bozo_exception)
        items = []
        for entry in feed.entries[:max_items]:
            title = entry.get("title", "(no title)")
            summary = (entry.get("summary", "") or entry.get("description", ""))[:220]
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


def fetch_quote(symbol):
    """Free, no-key quote via Yahoo Finance's public chart endpoint."""
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        meta = data["chart"]["result"][0]["meta"]
        price = meta.get("regularMarketPrice")
        prev = meta.get("chartPreviousClose") or meta.get("previousClose")
        if price is None or prev is None:
            return None
        pct = (price - prev) / prev * 100
        return {"price": price, "pct": pct}
    except Exception as e:
        print(f"  [skip] quote {symbol}: {e}", file=sys.stderr)
        return None


def describe_move(name, symbol):
    """Qualitative description of a move -- no exact prices/percentages,
    since those aren't useful to hear read aloud."""
    q = fetch_quote(symbol)
    if not q:
        return None
    pct = q["pct"]
    if abs(pct) < 0.15:
        return f"{name} is little changed"
    direction = "higher" if pct >= 0 else "lower"
    magnitude = abs(pct)
    if magnitude < 0.5:
        adverb = "slightly"
    elif magnitude < 1.5:
        adverb = "solidly"
    elif magnitude < 3:
        adverb = "sharply"
    else:
        adverb = "dramatically"
    return f"{name} is {adverb} {direction}"


def fetch_earnings():
    """Free earnings calendar via Nasdaq's public (unofficial, no-key)
    calendar endpoint. Sorted by market cap where available so the
    biggest names surface first. Returns None if the endpoint fails or
    has nothing for today -- Nasdaq occasionally blocks non-browser
    requests, so this is best-effort, not guaranteed."""
    try:
        url = f"https://api.nasdaq.com/api/calendar/earnings?date={TODAY.isoformat()}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
            "Accept": "application/json",
        }
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        rows = (data.get("data") or {}).get("rows") or []
        if not rows:
            return None

        def market_cap_value(row):
            raw = (row.get("marketCap") or "").replace("$", "").replace(",", "")
            try:
                return float(raw)
            except ValueError:
                return 0.0

        rows.sort(key=market_cap_value, reverse=True)
        names = []
        for r in rows[:5]:
            name = r.get("name") or r.get("symbol")
            if name:
                names.append(name)
        return names or None
    except Exception as e:
        print(f"  [skip] earnings calendar: {e}", file=sys.stderr)
        return None


def build_transcript():
    lines = [
        f"Good morning. Here's your markets and economy briefing for {TODAY.strftime('%A, %B %d')}.",
        "",
    ]

    # ---------------- 1. US market indices + major movers ----------------
    lines.append("Starting with the US markets.")
    moves = []
    for name, sym in [("The S&P 500", "^GSPC"), ("The Nasdaq", "^IXIC"), ("The Dow", "^DJI")]:
        m = describe_move(name, sym)
        if m:
            moves.append(m)
    gold = describe_move("Gold", "GC=F")
    eur = describe_move("The euro against the dollar", "EURUSD=X")
    gbp = describe_move("The pound against the dollar", "GBPUSD=X")
    for m in [gold, eur, gbp]:
        if m:
            moves.append(m)
    if moves:
        lines.append(". ".join(moves) + ".")

    movers = summarize(fetch_rss("MarketWatch Top Stories", RSS_SOURCES["MarketWatch Top Stories"]))
    if movers:
        lines.append(f"What's driving that, per MarketWatch: {movers}")

    cnbc = summarize(fetch_rss("CNBC Top News", RSS_SOURCES["CNBC Top News"]))
    if cnbc:
        lines.append(f"CNBC's top stories: {cnbc}")

    # ---------------- 2. Geopolitical / political risk ----------------
    lines.append("")
    lines.append("On geopolitical and political risk.")
    world = summarize(fetch_rss("BBC World", RSS_SOURCES["BBC World"]))
    if world:
        lines.append(f"From the BBC's world coverage: {world}")
    us_pol = summarize(fetch_rss("BBC Politics", RSS_SOURCES["BBC Politics"]))
    if us_pol:
        lines.append(f"On the political side: {us_pol}")

    # ---------------- 3. Fed / interest rates ----------------
    lines.append("")
    lines.append("On the Federal Reserve and interest rates.")
    fed = summarize(fetch_rss("Fed Press Releases", RSS_SOURCES["Fed Press Releases"]))
    if fed:
        lines.append(f"The Fed's own press releases show: {fed}")
    else:
        lines.append("No new Fed press releases today.")
    econ = summarize(fetch_rss("CNBC Economy", RSS_SOURCES["CNBC Economy"]))
    if econ:
        lines.append(f"On the broader economy, CNBC reports: {econ}")

    # ---------------- 4. EU / UK economy ----------------
    lines.append("")
    lines.append("Now to the EU, UK, and Dublin side.")
    biz = summarize(fetch_rss("BBC Business", RSS_SOURCES["BBC Business"]))
    if biz:
        lines.append(f"BBC Business covers: {biz}")
    rte_biz = summarize(fetch_rss("RTE Business", RSS_SOURCES["RTE Business"]))
    if rte_biz:
        lines.append(f"On the Dublin side, RTE Business reports: {rte_biz}")
    rte = summarize(fetch_rss("RTE News", RSS_SOURCES["RTE News"]))
    if rte:
        lines.append(f"RTE News adds: {rte}")

    # ---------------- 5. Earnings calendar ----------------
    lines.append("")
    earnings = fetch_earnings()
    if earnings:
        lines.append("On earnings, reporting today: " + ", ".join(earnings) + ".")
    else:
        lines.append(
            "No earnings calendar data came through today -- worth checking "
            "Nasdaq's free earnings calendar directly if you want specifics."
        )

    # ---------------- 6. Asia (brief) ----------------
    lines.append("")
    lines.append("Briefly on Asia.")
    asia_moves = []
    for name, sym in ASIA_TICKERS.items():
        m = describe_move(name, sym)
        if m:
            asia_moves.append(m)
    if asia_moves:
        lines.append(". ".join(asia_moves) + ".")
    asia_news = summarize(fetch_rss("CNBC Asia Markets", RSS_SOURCES["CNBC Asia Markets"]))
    if asia_news:
        lines.append(f"CNBC Asia adds: {asia_news}")

    lines.append("")
    lines.append("That's the briefing for this morning.")

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
    return resp.content


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
        "subject": f"Morning Markets Briefing (audio) — {TODAY.strftime('%A, %B %d, %Y')}",
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
