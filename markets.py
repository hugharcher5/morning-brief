"""
The market section of the briefing: real moves, sized against normal days.

Every asset's latest daily move is compared with the standard deviation of its
daily moves over the past year (about 252 trading days). That z-score decides
how much airtime it gets:

    under 1 sigma      one quick line ("gold up 0.2 percent")
    1 to 1.5 sigma     a normal mention
    over 1.5 sigma     a notable move: say why it happened

Prices are measured in percent, yields and overnight rates in basis points.

Sources, all free and keyless:
    CNBC's quote history API    indices, yields, gold spot, EUR/USD
    New York Fed                SOFR and the effective fed funds rate
    ECB Data Portal             euro short-term rate (€STR), deposit rate
    Yahoo Finance               30-day fed funds futures, for what's priced in
    BLS and BEA release feeds   US jobs, inflation and GDP
"""

import datetime
import statistics
import sys

import feedparser
import requests

UA = {"User-Agent": "Mozilla/5.0 (morning-brief; +https://github.com/hugharcher5/morning-brief)"}
LOOKBACK = 252            # trading days in a year
NOTABLE_SIGMA = 1.5       # explain anything bigger than this
QUIET_SIGMA = 1.0         # one quick line for anything smaller

# (spoken name, CNBC symbol, "pct" for prices or "bp" for yields)
ASSETS = [
    ("US 10-year Treasury yield", "US10Y", "bp"),
    ("Swiss 10-year yield", "CH10Y-CH", "bp"),
    ("Dow Jones Industrial Average", ".DJI", "pct"),
    ("S&P 500", ".SPX", "pct"),
    ("Nasdaq Composite", ".IXIC", "pct"),
    ("MSCI World", ".MSCIWO", "pct"),
    ("MSCI Emerging Markets", ".MSCIEF", "pct"),
    ("Euro Stoxx 50", ".STOXX50E", "pct"),
    ("Gold spot", "XAU=", "pct"),
    ("EUR/USD", "EUR=", "pct"),
]

# Published calendars (federalreserve.gov, ecb.europa.eu). Decision day only.
FOMC_DECISIONS = [
    "2026-10-28", "2026-12-09",
    "2027-01-27", "2027-03-17", "2027-04-28", "2027-06-09",
    "2027-07-28", "2027-09-15", "2027-10-27", "2027-12-08",
]
ECB_DECISIONS = [
    "2026-10-29", "2026-12-17",
    "2027-02-04", "2027-03-18", "2027-04-29", "2027-06-10",
    "2027-07-22", "2027-09-09", "2027-10-28", "2027-12-16",
]

FUTURES_MONTHS = "FGHJKMNQUVXZ"   # CME month codes, January to December

RELEASE_FEEDS = [
    ("US jobs report", "https://www.bls.gov/feed/empsit.rss", None),
    ("US CPI", "https://www.bls.gov/feed/cpi.rss", None),
    ("US GDP and PCE", "https://apps.bea.gov/rss/rss.xml", ("GDP", "Personal Income")),
]


def _warn(what, err):
    print(f"  [skip] {what}: {err}", file=sys.stderr)


def _get(url, **kw):
    # bls.gov refuses user agents that contain a URL
    headers = {"User-Agent": "Mozilla/5.0 (morning-brief)"} if "bls.gov" in url else UA
    for attempt in range(3):   # the odd connection drops; try again before giving up
        try:
            resp = requests.get(url, headers=headers, timeout=15, **kw)
            resp.raise_for_status()
            return resp
        except requests.ConnectionError:
            if attempt == 2:
                raise


def _measure(name, closes, unit):
    """Latest move, its size in sigmas, and a one-line summary."""
    closes = closes[-(LOOKBACK + 2):]
    if len(closes) < 30:
        raise ValueError("not enough history")
    if unit == "bp":
        moves = [(b - a) * 100 for a, b in zip(closes, closes[1:])]
    else:
        moves = [(b - a) / a * 100 for a, b in zip(closes, closes[1:])]
    today, history = moves[-1], moves[:-1]
    sigma = statistics.pstdev(history) or 1e-9
    z = today / sigma
    return {"name": name, "level": closes[-1], "move": today, "unit": unit,
            "sigma": sigma, "z": z, "notable": abs(z) >= NOTABLE_SIGMA}


def fetch_asset(name, symbol, unit):
    try:
        bars = _get(f"https://ts-api.cnbc.com/harmony/app/charts/1Y.json?symbol={symbol}").json()
        by_day = {}
        for bar in bars["barData"]["priceBars"]:
            by_day[bar["tradeTime"][:8]] = float(bar["close"])   # last bar of each day wins
        closes = [by_day[d] for d in sorted(by_day)]
        return _measure(name, closes, unit)
    except Exception as e:
        _warn(name, e)
        return None


def fetch_sofr():
    try:
        rows = _get(f"https://markets.newyorkfed.org/api/rates/secured/sofr/last/{LOOKBACK + 2}.json").json()["refRates"]
        closes = [r["percentRate"] for r in sorted(rows, key=lambda r: r["effectiveDate"])]
        return _measure("SOFR", closes, "bp")
    except Exception as e:
        _warn("SOFR", e)
        return None


def fetch_estr():
    try:
        text = _get("https://data-api.ecb.europa.eu/service/data/EST/B.EU000A2X2A25.WT",
                    params={"format": "csvdata", "lastNObservations": LOOKBACK + 2}).text
        lines = text.strip().splitlines()
        header = lines[0].split(",")
        i_date, i_val = header.index("TIME_PERIOD"), header.index("OBS_VALUE")
        rows = sorted((l.split(",")[i_date], float(l.split(",")[i_val])) for l in lines[1:])
        return _measure("Euro short-term rate (€STR)", [v for _, v in rows], "bp")
    except Exception as e:
        _warn("€STR", e)
        return None


def _next(dates, today):
    for d in dates:
        day = datetime.date.fromisoformat(d)
        if day >= today:
            return day
    return None


def _fed_funds_future(year, month):
    """Implied average fed funds rate for a month, from its 30-day futures price."""
    symbol = f"ZQ{FUTURES_MONTHS[month - 1]}{year % 100:02d}.CBT"
    meta = _get(f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}").json()["chart"]["result"][0]["meta"]
    return 100 - meta["regularMarketPrice"]


def fed_outlook(today):
    """Next two FOMC decisions and how much easing the futures market prices for each."""
    try:
        effr = _get("https://markets.newyorkfed.org/api/rates/unsecured/effr/last/1.json").json()["refRates"][0]["percentRate"]
        out, prev_rate = [], effr
        upcoming = [datetime.date.fromisoformat(d) for d in FOMC_DECISIONS
                    if datetime.date.fromisoformat(d) >= today][:2]
        for day in upcoming:
            # The month after the meeting holds the full post-decision rate
            y, m = (day.year + 1, 1) if day.month == 12 else (day.year, day.month + 1)
            implied = _fed_funds_future(y, m)
            change_bp = (implied - prev_rate) * 100
            out.append({"date": day, "implied": implied, "change_bp": change_bp})
            prev_rate = implied
        return {"effr": effr, "meetings": out}
    except Exception as e:
        _warn("Fed pricing", e)
        return None


def ecb_outlook(today):
    try:
        text = _get("https://data-api.ecb.europa.eu/service/data/FM/D.U2.EUR.4F.KR.DFR.LEV",
                    params={"format": "csvdata", "lastNObservations": 1}).text
        lines = text.strip().splitlines()
        rate = float(lines[1].split(",")[lines[0].split(",").index("OBS_VALUE")])
    except Exception as e:
        _warn("ECB deposit rate", e)
        rate = None
    return {"deposit_rate": rate, "next": _next(ECB_DECISIONS, today)}


def recent_releases(today, days=3):
    """US data releases from the last few days, straight from the agencies' feeds."""
    found = []
    for label, url, keep in RELEASE_FEEDS:
        try:
            feed = feedparser.parse(_get(url).content)
        except Exception as e:
            _warn(label, e)
            continue
        for entry in feed.entries:
            when = entry.get("updated_parsed") or entry.get("published_parsed")
            if not when:
                continue
            day = datetime.date(*when[:3])
            title = entry.get("title", "").strip()
            if (today - day).days <= days and (not keep or any(k in title for k in keep)):
                found.append(f"{label} ({day:%A %d %B}): {title}")
    return found


def gather_markets(today):
    assets = [fetch_asset(*a) for a in ASSETS]
    rates = [fetch_sofr(), fetch_estr()]
    return {
        "assets": [a for a in assets + rates if a],
        "fed": fed_outlook(today),
        "ecb": ecb_outlook(today),
        "releases": recent_releases(today),
    }


# --- Writing the numbers down --------------------------------------------------

def fmt_move(a):
    sign = "+" if a["move"] >= 0 else "-"
    if a["unit"] == "bp":
        return f"{sign}{abs(a['move']):.1f}bp to {a['level']:.3f}%"
    level = f"{a['level']:.4f}" if a["level"] < 10 else f"{a['level']:,.2f}"
    return f"{sign}{abs(a['move']):.2f}% to {level}"


def markets_as_text(m):
    lines = ["Market moves (latest close vs previous close; sigma = size of the move "
             "against the past year's daily moves):"]
    for a in m["assets"]:
        tag = "NOTABLE, explain why" if a["notable"] else ("normal" if abs(a["z"]) >= QUIET_SIGMA else "quiet")
        lines.append(f"- {a['name']}: {fmt_move(a)} ({abs(a['z']):.1f} sigma, {tag})")
    fed = m.get("fed")
    if fed:
        lines.append(f"\nFed: effective fed funds rate {fed['effr']:.2f}%.")
        for mt in fed["meetings"]:
            odds = abs(mt["change_bp"]) / 25
            move = "hike" if mt["change_bp"] > 0 else "cut"
            lines.append(f"- FOMC decision {mt['date']:%A %d %B}: fed funds futures imply {mt['change_bp']:+.0f}bp, "
                         f"roughly a {odds:.0%} chance of a 25bp {move}, taking the rate to about {mt['implied']:.2f}%")
    ecb = m.get("ecb") or {}
    if ecb.get("next"):
        rate = f"deposit rate {ecb['deposit_rate']:.2f}%, " if ecb.get("deposit_rate") is not None else ""
        lines.append(f"\nECB: {rate}next decision {ecb['next']:%A %d %B}.")
    if m.get("releases"):
        lines.append("\nRecent US data releases:")
        lines += [f"- {r}" for r in m["releases"]]
    return "\n".join(lines)


def spoken_move(a):
    """Plain-English version for the no-AI template."""
    direction = "up" if a["move"] >= 0 else "down"
    if a["unit"] == "bp":
        return f"{a['name']} {direction} {abs(a['move']):.1f} basis points, at {a['level']:.2f} percent"
    return f"{a['name']} {direction} {abs(a['move']):.2f} percent"
