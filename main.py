from fastapi import FastAPI, Request, Form, Query, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from google.oauth2 import service_account
from datetime import datetime, timedelta
from twilio.rest import Client
import httpx
import pytz
import os
import json
import re
import time
import asyncio
import requests
from bs4 import BeautifulSoup

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/calendar"
]

SPREADSHEET_ID = "1kdREpipKfSYCsj03csvG9brFYeQQu18Yxkp5DBRsPbo"
CALENDAR_ID    = "chbilal.2332@gmail.com"
TIMEZONE       = "America/Chicago"

TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN  = os.environ.get("TWILIO_AUTH_TOKEN")
TWILIO_PHONE       = os.environ.get("TWILIO_PHONE", "+17373345444")
AGENT_PHONE        = os.environ.get("AGENT_PHONE", "+17373345444")

twilio_client       = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
GOOGLE_MAPS_API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY")

# ── FSBO Scraper Config ────────────────────────────────────────────────────
RETELL_API_KEY     = os.environ.get("RETELL_API_KEY")
RETELL_FROM_NUMBER = os.environ.get("RETELL_FROM_NUMBER", "+17373345444")
RETELL_AGENT_ID    = os.environ.get("RETELL_FSBO_AGENT_ID")

SCRAPER_API_KEY = os.environ.get("SCRAPER_API_KEY")

CL_FSBO_URL = (
    "https://austin.craigslist.org/search/rea"
    "?sale_date=all&hasPic=1&srchType=T&purveyor=owner&lang=en&cc=us"
)
CL_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://www.google.com/",
}
PROSPECTS_SHEET_TAB = "Prospects"
PROSPECTS_HEADERS   = [
    "Date Scraped", "Title", "Price", "Location",
    "Phone", "URL", "Bedrooms", "Bathrooms",
    "SqFt", "Description Snippet", "Status"
]

_PHONE_RE = re.compile(r"(\(?\d{3}\)?[\s.\-]?\d{3}[\s.\-]?\d{4})")
_BED_RE   = re.compile(r"(\d+)\s*(?:bd|bed|bedroom)", re.I)
_BATH_RE  = re.compile(r"(\d+(?:\.\d+)?)\s*(?:ba|bath|bathroom)", re.I)
_SQFT_RE  = re.compile(r"([\d,]+)\s*(?:sq\s*ft|sqft|sf)", re.I)

# ── Agent Toggle State ─────────────────────────────────────────────────────
agent_state = {
    "manual_override": None,
    "meeting_until":   None
}

WORKING_HOURS = {
    "monday":    (9, 18),
    "tuesday":   (9, 18),
    "wednesday": (9, 18),
    "thursday":  (9, 18),
    "friday":    (9, 18),
}

NEIGHBORHOOD_DATA = {
    "south congress":  {"vibe": "Trendy, artsy, walkable.", "demographics": "Young professionals, ages 25-40.", "crime": "Low to moderate.", "avg_price": "$620,000", "best_for": "First-time buyers wanting walkable urban lifestyle."},
    "hyde park":       {"vibe": "Quiet, historic, tree-lined.", "demographics": "Students, professors, families.", "crime": "Low.", "avg_price": "$580,000", "best_for": "Families wanting charm and quiet."},
    "mueller":         {"vibe": "Modern planned community, family friendly.", "demographics": "Young families, ages 30-45.", "crime": "Very low.", "avg_price": "$550,000", "best_for": "Families wanting new construction."},
    "east austin":     {"vibe": "Hip, eclectic, best food and bar scene.", "demographics": "Millennials, artists.", "crime": "Moderate, improving.", "avg_price": "$650,000", "best_for": "Buyers wanting culture and investment potential."},
    "zilker":          {"vibe": "Outdoor paradise near Barton Springs.", "demographics": "Active professionals, ages 28-45.", "crime": "Low.", "avg_price": "$900,000", "best_for": "Outdoor enthusiasts wanting premium location."},
    "domain":          {"vibe": "Upscale tech hub, luxury shopping.", "demographics": "Tech workers, young professionals.", "crime": "Very low.", "avg_price": "$480,000", "best_for": "Tech workers at Apple, Dell, Google."},
    "brentwood":       {"vibe": "Quiet, established, classic Austin.", "demographics": "Long-term families and retirees.", "crime": "Very low.", "avg_price": "$700,000", "best_for": "Buyers wanting stability close to downtown."},
    "south lamar":     {"vibe": "Vibrant, restaurant-heavy, great nightlife.", "demographics": "Young professionals, ages 25-38.", "crime": "Low to moderate.", "avg_price": "$680,000", "best_for": "Buyers who love food and Austin culture."},
    "cedar park":      {"vibe": "Suburban, family-oriented, great schools.", "demographics": "Families with children, ages 30-50.", "crime": "Very low.", "avg_price": "$420,000", "best_for": "Families wanting space and top schools."},
    "round rock":      {"vibe": "Large suburb, great for families.", "demographics": "Families and corporate workers.", "crime": "Very low.", "avg_price": "$390,000", "best_for": "Budget-conscious families."},
    "westlake":        {"vibe": "Affluent, prestigious, rolling hills.", "demographics": "High-income families.", "crime": "Extremely low.", "avg_price": "$1,400,000", "best_for": "Luxury buyers wanting top schools."},
    "travis heights":  {"vibe": "Charming, hilly, eclectic.", "demographics": "Artists and long-term Austinites.", "crime": "Low.", "avg_price": "$750,000", "best_for": "Buyers wanting character homes."},
}


# ═══════════════════════════════════════════════════════════════════════════
# ── Helpers ────────────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════

def get_credentials():
    creds_dict = json.loads(os.environ.get("GOOGLE_CREDENTIALS_JSON"))
    return service_account.Credentials.from_service_account_info(creds_dict, scopes=SCOPES)

def parse_money(value: str) -> int:
    v = str(value).lower().replace("$", "").replace(",", "").strip()
    word_map = {"one":1,"two":2,"three":3,"four":4,"five":5,"six":6,"seven":7,"eight":8,"nine":9,"ten":10}
    if "million" in v:
        num = v.replace("million","").strip()
        return int(float(word_map.get(num, num)) * 1_000_000)
    elif "thousand" in v or v.endswith("k"):
        num = v.replace("thousand","").replace("k","").strip()
        return int(float(num) * 1_000)
    return int(float(v.replace(" ","")))

def send_sms(to: str, body: str):
    try:
        msg = twilio_client.messages.create(body=body, from_=TWILIO_PHONE, to=to)
        print(f"SMS sent: {msg.sid}")
    except Exception as e:
        print(f"SMS error: {e}")

def is_within_working_hours() -> bool:
    tz  = pytz.timezone(TIMEZONE)
    now = datetime.now(tz)
    day = now.strftime("%A").lower()
    hours = WORKING_HOURS.get(day)
    if hours is None:
        return False
    return hours[0] <= now.hour < hours[1]

def should_ai_handle_call() -> bool:
    tz  = pytz.timezone(TIMEZONE)
    now = datetime.now(tz)
    if agent_state["meeting_until"]:
        if now < agent_state["meeting_until"]:
            return True
        else:
            agent_state["meeting_until"] = None
    if agent_state["manual_override"] is not None:
        return agent_state["manual_override"]
    return not is_within_working_hours()


# ═══════════════════════════════════════════════════════════════════════════
# ── FSBO Scraper Helpers ───────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════

def _scraper_url(target: str) -> str:
    """Route a URL through ScraperAPI to bypass Craigslist IP blocking."""
    return f"http://api.scraperapi.com?api_key={SCRAPER_API_KEY}&url={target}"

def _get_sheets_service():
    from googleapiclient.discovery import build
    return build("sheets", "v4", credentials=get_credentials())

def _ensure_prospects_tab(service) -> None:
    meta = service.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
    existing = [s["properties"]["title"] for s in meta.get("sheets", [])]
    if PROSPECTS_SHEET_TAB not in existing:
        service.spreadsheets().batchUpdate(
            spreadsheetId=SPREADSHEET_ID,
            body={"requests": [{"addSheet": {"properties": {"title": PROSPECTS_SHEET_TAB}}}]}
        ).execute()
        service.spreadsheets().values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=f"{PROSPECTS_SHEET_TAB}!A1",
            valueInputOption="RAW",
            body={"values": [PROSPECTS_HEADERS]}
        ).execute()
        print(f"Created '{PROSPECTS_SHEET_TAB}' tab")

def _existing_prospect_urls(service) -> set:
    result = service.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{PROSPECTS_SHEET_TAB}!F2:F"
    ).execute()
    return {r[0] for r in result.get("values", []) if r}

def _fetch_listings_from_search() -> list:
    """Scrape title, price, location, URL directly from search results page."""
    url = _scraper_url(CL_FSBO_URL) if SCRAPER_API_KEY else CL_FSBO_URL
    resp = requests.get(url, headers=CL_HEADERS, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    items = soup.select("li.cl-static-search-result")
    print(f"Found {len(items)} listing links on Craigslist")
    results = []
    for item in items:
        a = item.select_one("a")
        if not a:
            continue
        results.append({
            "title":    item.get("title", "N/A"),
            "url":      a.get("href", ""),
            "price":    (item.select_one(".price") or type('', (), {'get_text': lambda *a, **k: 'N/A'})()).get_text(strip=True),
            "location": (item.select_one(".location") or type('', (), {'get_text': lambda *a, **k: 'N/A'})()).get_text(strip=True),
        })
    return results

def _parse_listing(url: str) -> dict | None:
    try:
        fetch_url = _scraper_url(url) if SCRAPER_API_KEY else url
        resp = requests.get(fetch_url, headers=CL_HEADERS, timeout=30)
        if resp.status_code != 200:
            return None
        soup = BeautifulSoup(resp.text, "html.parser")

        title_tag = soup.select_one("#titletextonly")
        title     = title_tag.get_text(strip=True) if title_tag else "N/A"

        price_tag = soup.select_one(".price")
        price     = price_tag.get_text(strip=True) if price_tag else "N/A"

        loc_tag   = soup.select_one(".mapaddress")
        location  = loc_tag.get_text(strip=True) if loc_tag else "N/A"

        body_tag  = soup.select_one("#postingbody")
        body      = body_tag.get_text(" ", strip=True) if body_tag else ""

        phone_m   = _PHONE_RE.search(body)
        phone     = phone_m.group(1) if phone_m else "N/A"

        beds      = (m := _BED_RE.search(body + " " + title))  and m.group(1) or "N/A"
        baths     = (m := _BATH_RE.search(body + " " + title)) and m.group(1) or "N/A"
        sqft_m    = _SQFT_RE.search(body + " " + title)
        sqft      = sqft_m.group(1).replace(",", "") if sqft_m else "N/A"
        snippet   = body[:200].replace("\n", " ").strip()

        return {"title": title, "price": price, "location": location,
                "phone": phone, "beds": beds, "baths": baths,
                "sqft": sqft, "snippet": snippet}
    except Exception as exc:
        print(f"Parse error {url}: {exc}")
        return None

def run_fsbo_scraper() -> dict:
    service = _get_sheets_service()
    _ensure_prospects_tab(service)
    seen     = _existing_prospect_urls(service)
    listings = _fetch_listings_from_search()
    new_rows = []

    for listing in listings:          # ← same level as 'service' above
        url = listing["url"]
        if not url or url in seen:
            continue

        skip_keywords = ["warehouse", "office space", "commercial", "business", "storage", "cubework"]
        if any(kw in listing["title"].lower() for kw in skip_keywords):
            continue

        row = [
            datetime.now(pytz.timezone(TIMEZONE)).strftime("%Y-%m-%d %H:%M"),
            listing["title"],
            listing["price"],
            listing["location"],
            "N/A",   # phone - hidden by Craigslist JS
            url,
            "N/A",   # beds
            "N/A",   # baths
            "N/A",   # sqft
            "",      # snippet
            "New"
        ]
        new_rows.append(row)
        seen.add(url)

    if new_rows:
        service.spreadsheets().values().append(
            spreadsheetId=SPREADSHEET_ID,
            range=f"{PROSPECTS_SHEET_TAB}!A:K",
            valueInputOption="USER_ENTERED",
            body={"values": new_rows}
        ).execute()

    summary = {"scraped": len(listings), "new": len(new_rows)}
    print(f"FSBO scrape done — {summary}")
    return summary


# ═══════════════════════════════════════════════════════════════════════════
# ── Health Check ───────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/")
def root():
    return {"status": "Austin RE Agent API is running"}


# ═══════════════════════════════════════════════════════════════════════════
# ── Agent Status ───────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/agent/status")
def get_agent_status():
    tz  = pytz.timezone(TIMEZONE)
    now = datetime.now(tz)
    ai_on = should_ai_handle_call()
    meeting_active = bool(agent_state["meeting_until"] and now < agent_state["meeting_until"])
    meeting_remaining = ""
    if meeting_active:
        meeting_remaining = agent_state["meeting_until"].strftime("%-I:%M %p")
    return {
        "enabled":              ai_on,
        "mode":                 "meeting" if meeting_active else "manual" if agent_state["manual_override"] is not None else "schedule",
        "within_working_hours": is_within_working_hours(),
        "meeting_active":       meeting_active,
        "meeting_remaining":    meeting_remaining
    }


# ═══════════════════════════════════════════════════════════════════════════
# ── Dashboard Control Endpoints ────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════

@app.post("/agent/enable")
def agent_enable():
    agent_state["manual_override"] = True
    agent_state["meeting_until"]   = None
    return {"ok": True, "enabled": True, "mode": "manual"}

@app.post("/agent/disable")
def agent_disable():
    agent_state["manual_override"] = False
    agent_state["meeting_until"]   = None
    return {"ok": True, "enabled": False, "mode": "manual"}

@app.post("/agent/schedule")
def agent_schedule():
    agent_state["manual_override"] = None
    agent_state["meeting_until"]   = None
    ai_on = should_ai_handle_call()
    return {"ok": True, "enabled": ai_on, "mode": "schedule"}

@app.post("/agent/meeting")
def agent_meeting(hours: int = Query(default=1)):
    tz    = pytz.timezone(TIMEZONE)
    until = datetime.now(tz) + timedelta(hours=hours)
    agent_state["meeting_until"]   = until
    agent_state["manual_override"] = None
    return {"ok": True, "meeting_until": until.isoformat(), "meeting_active": True}


# ═══════════════════════════════════════════════════════════════════════════
# ── SMS Toggle ─────────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════

@app.post("/sms_toggle")
async def sms_toggle(request: Request):
    data   = await request.form()
    body   = data.get("Body", "").strip().lower()
    sender = data.get("From", "").strip()

    if sender != AGENT_PHONE:
        return {"status": "unauthorized"}

    tz  = pytz.timezone(TIMEZONE)
    now = datetime.now(tz)

    if body.startswith("meeting"):
        parts = body.split()
        try:    hours = int(parts[1]) if len(parts) > 1 else 1
        except: hours = 1
        agent_state["meeting_until"]   = now + timedelta(hours=hours)
        agent_state["manual_override"] = None
        until_str = agent_state["meeting_until"].strftime("%I:%M %p")
        send_sms(AGENT_PHONE,
            f"Meeting mode ON for {hours} hour(s).\n"
            f"Ashley handles calls until {until_str}.\n"
            f"She turns OFF automatically after."
        )

    elif body == "on":
        agent_state["manual_override"] = True
        agent_state["meeting_until"]   = None
        send_sms(AGENT_PHONE,
            "Ashley is now ON (manual override).\n"
            "She handles all calls until you text OFF or SCHEDULE."
        )

    elif body == "off":
        agent_state["manual_override"] = False
        agent_state["meeting_until"]   = None
        send_sms(AGENT_PHONE,
            "Ashley is now OFF (manual override).\n"
            "Calls ring directly to you until you text ON or SCHEDULE."
        )

    elif body == "schedule":
        agent_state["manual_override"] = None
        agent_state["meeting_until"]   = None
        send_sms(AGENT_PHONE,
            "Ashley is back on AUTO SCHEDULE.\n"
            "AI OFF during working hours.\n"
            "AI ON outside hours and on days off."
        )

    elif body == "status":
        ai_on = should_ai_handle_call()
        if agent_state["meeting_until"] and now < agent_state["meeting_until"]:
            mode = f"Meeting mode ends at {agent_state['meeting_until'].strftime('%I:%M %p')}"
        elif agent_state["manual_override"] is True:
            mode = "Manual override ON"
        elif agent_state["manual_override"] is False:
            mode = "Manual override OFF"
        else:
            mode = "Auto schedule"
        send_sms(AGENT_PHONE,
            f"Ashley is {'ON' if ai_on else 'OFF'}\nMode: {mode}\n\n"
            "Commands:\nON / OFF / MEETING 2 / SCHEDULE / STATUS"
        )

    else:
        send_sms(AGENT_PHONE,
            "Unknown command.\n\nAvailable:\n"
            "ON — force on\nOFF — force off\n"
            "MEETING 2 — on for 2 hrs\nSCHEDULE — auto\nSTATUS — check"
        )

    return {"status": "ok"}


# ═══════════════════════════════════════════════════════════════════════════
# ── Capture Lead ───────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════

@app.post("/capture_lead")
async def capture_lead(request: Request):
    from googleapiclient.discovery import build
    data    = await request.json()
    service = build("sheets", "v4", credentials=get_credentials())

    row = [[
        datetime.now(pytz.timezone(TIMEZONE)).strftime("%Y-%m-%d %H:%M:%S"),
        data.get("name", ""),
        data.get("phone", ""),
        data.get("email", ""),
        data.get("intent", ""),
        data.get("budget", ""),
        data.get("timeline", ""),
        data.get("lead_quality", "unknown"),
        data.get("notes", "")
    ]]

    service.spreadsheets().values().append(
        spreadsheetId=SPREADSHEET_ID, range="Leads!A:I",
        valueInputOption="RAW", body={"values": row}
    ).execute()

    lq    = data.get("lead_quality", "").upper()
    emoji = "🔥" if lq == "HOT" else "🌡️" if lq == "WARM" else "❄️"
    send_sms(AGENT_PHONE,
        f"{emoji} New {lq} Lead!\n"
        f"Name: {data.get('name','')}\nPhone: {data.get('phone','')}\n"
        f"Budget: {data.get('budget','')}\nIntent: {data.get('intent','')}\n"
        f"Timeline: {data.get('timeline','')}\nNotes: {data.get('notes','')}"
    )
    return {"status": "success", "message": "Lead captured"}


# ═══════════════════════════════════════════════════════════════════════════
# ── Book Showing ───────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════

@app.post("/book_showing")
async def book_showing(request: Request):
    from googleapiclient.discovery import build
    data         = await request.json()
    cal_service  = build("calendar", "v3", credentials=get_credentials())
    tz           = pytz.timezone(TIMEZONE)
    current_year = datetime.now(tz).year

    try:
        start_str = data.get("datetime", "").strip()
        if not start_str:
            return {"status": "error", "message": "I didn't receive a date. What date and time works for you?"}
        if str(current_year) not in start_str:
            start_str = f"{current_year}-{start_str}T10:00:00" if "T" not in start_str else start_str
        try:
            start_time = datetime.strptime(start_str, "%Y-%m-%dT%H:%M:%S")
        except ValueError:
            start_time = datetime.strptime(start_str, "%Y-%m-%d").replace(hour=10, minute=0, second=0)
        start_time = tz.localize(start_time)
    except Exception:
        return {"status": "error", "message": "I couldn't understand that date. Try: April 13th at 2pm."}

    end_time = start_time + timedelta(hours=1)
    event = {
        "summary":     f"Property Showing — {data.get('name', 'Prospect')}",
        "description": f"Phone: {data.get('phone','')}\nBudget: {data.get('budget','')}\nNotes: {data.get('notes','')}",
        "start":       {"dateTime": start_time.isoformat(), "timeZone": TIMEZONE},
        "end":         {"dateTime": end_time.isoformat(),   "timeZone": TIMEZONE},
    }
    cal_service.events().insert(calendarId=CALENDAR_ID, body=event).execute()

    send_sms(AGENT_PHONE,
        f"Showing Booked!\nName: {data.get('name','')}\nPhone: {data.get('phone','')}\n"
        f"Time: {start_time.strftime('%B %d at %I:%M %p')}\n"
        f"Budget: {data.get('budget','')}\nNotes: {data.get('notes','')}"
    )
    return {"status": "success", "message": f"Showing booked for {start_time.strftime('%B %d at %I:%M %p')}"}


# ═══════════════════════════════════════════════════════════════════════════
# ── Search Listings ────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════

@app.post("/search_listings")
async def search_listings(request: Request):
    from googleapiclient.discovery import build
    data       = await request.json()
    budget_raw = data.get("budget", "")
    area       = data.get("area", "").lower().strip()
    beds_raw   = data.get("beds", "")

    try:    budget = parse_money(budget_raw)
    except: budget = 99_999_999
    try:    beds = int(str(beds_raw).strip())
    except: beds = 0

    service = build("sheets", "v4", credentials=get_credentials())
    result  = service.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID, range="Listings!A:I"
    ).execute()
    rows = result.get("values", [])

    if len(rows) <= 1:
        return {"status": "no_listings", "message": "No listings available right now."}

    headers  = rows[0]
    listings = []
    for row in rows[1:]:
        while len(row) < len(headers): row.append("")
        listing = dict(zip(headers, row))
        if listing.get("Status","").lower() != "available": continue
        try:    price = parse_money(listing.get("Price","0"))
        except: continue
        try:    listing_beds = int(listing.get("Beds","0"))
        except: listing_beds = 0
        if price > budget: continue
        if area and area not in listing.get("Area","").lower(): continue
        if beds and listing_beds < beds: continue
        listings.append({
            "address": listing.get("Address",""), "area":  listing.get("Area",""),
            "price":   listing.get("Price",""),   "beds":  listing.get("Beds",""),
            "baths":   listing.get("Baths",""),   "sqft":  listing.get("SqFt",""),
            "notes":   listing.get("Notes","")
        })

    if not listings:
        return {"status": "no_match", "message": "No listings found matching those criteria."}

    top     = listings[:3]
    summary = [
        f"{l['address']} in {l['area']} — {l['price']}, "
        f"{l['beds']} bed/{l['baths']} bath, {l['sqft']} sqft. {l['notes']}"
        for l in top
    ]

    send_sms(AGENT_PHONE,
        f"Listing Search!\nArea: {area or 'Any'}\nBudget: {budget_raw}\n"
        f"Beds: {beds_raw or 'Any'}\nMatches: {len(top)}"
    )
    return {"status": "success", "count": len(top), "listings": top, "summary": " | ".join(summary)}


# ═══════════════════════════════════════════════════════════════════════════
# ── Neighborhood Intel ─────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════

@app.post("/neighborhood_intel")
async def neighborhood_intel(request: Request):
    data         = await request.json()
    neighborhood = data.get("neighborhood", "").lower().strip()

    matched = next((k for k in NEIGHBORHOOD_DATA if k in neighborhood or neighborhood in k), None)
    if not matched:
        available = ", ".join([n.title() for n in NEIGHBORHOOD_DATA.keys()])
        return {"status": "not_found", "message": f"I don't have data for that area yet. I cover: {available}."}

    info = NEIGHBORHOOD_DATA[matched]

    commute_text = "unavailable"
    try:
        maps_url = (
            f"https://maps.googleapis.com/maps/api/distancematrix/json"
            f"?origins={matched.replace(' ','+')}+Austin+TX"
            f"&destinations=Downtown+Austin+TX&mode=driving&key={GOOGLE_MAPS_API_KEY}"
        )
        async with httpx.AsyncClient() as client:
            commute_text = (await client.get(maps_url)).json()["rows"][0]["elements"][0]["duration"]["text"]
    except Exception as e:
        print(f"Maps error: {e}")

    nearby_text = "unavailable"
    try:
        places_url = (
            f"https://maps.googleapis.com/maps/api/place/textsearch/json"
            f"?query=restaurants+in+{matched.replace(' ','+')}+Austin+TX&key={GOOGLE_MAPS_API_KEY}"
        )
        async with httpx.AsyncClient() as client:
            results = (await client.get(places_url)).json().get("results", [])[:3]
            if results: nearby_text = ", ".join([r["name"] for r in results])
    except Exception as e:
        print(f"Places error: {e}")

    return {
        "status":              "success",
        "neighborhood":        matched.title(),
        "avg_price":           info["avg_price"],
        "vibe":                info["vibe"],
        "crime":               info["crime"],
        "demographics":        info["demographics"],
        "commute_to_downtown": commute_text,
        "nearby_restaurants":  nearby_text,
        "best_for":            info["best_for"],
        "summary": (
            f"{matched.title()}: {info['vibe']} Avg price: {info['avg_price']}. "
            f"Crime: {info['crime']} Demographics: {info['demographics']} "
            f"Commute downtown: {commute_text}. Nearby: {nearby_text}. "
            f"Best for: {info['best_for']}"
        )
    }


# ═══════════════════════════════════════════════════════════════════════════
# ── Web Call Token ─────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════

@app.post("/create_web_call")
async def create_web_call(request: Request):
    data     = await request.json()
    agent_id = data.get("agent_id", "")
    async with httpx.AsyncClient() as client:
        res = await client.post(
            "https://api.retellai.com/v2/create-web-call",
            headers={
                "Authorization": f"Bearer {os.environ.get('RETELL_API_KEY')}",
                "Content-Type": "application/json"
            },
            json={"agent_id": agent_id}
        )
    return res.json()


# ═══════════════════════════════════════════════════════════════════════════
# ── FSBO Prospects Endpoints ───────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════

@app.post("/scrape_fsbo")
async def scrape_fsbo(background_tasks: BackgroundTasks):
    background_tasks.add_task(run_fsbo_scraper)
    return {"ok": True, "message": "FSBO scrape started in background. Check the Prospects sheet in ~60s."}


@app.get("/get_prospects")
async def get_prospects(status: str = Query(default="all")):
    service = _get_sheets_service()
    _ensure_prospects_tab(service)

    result = service.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{PROSPECTS_SHEET_TAB}!A2:K"
    ).execute()
    rows = result.get("values", [])

    prospects = []
    for i, r in enumerate(rows):
        while len(r) < 11:
            r.append("")
        p = {
            "row_index":  i + 2,
            "date_saved": r[0],
            "title":      r[1],
            "price":      r[2],
            "location":   r[3],
            "phone":      r[4],
            "url":        r[5],
            "beds":       r[6],
            "baths":      r[7],
            "sqft":       r[8],
            "snippet":    r[9],
            "status":     r[10] or "New",
        }
        if status == "all" or p["status"] == status:
            prospects.append(p)

    return {"ok": True, "count": len(prospects), "prospects": prospects}


@app.post("/call_prospect")
async def call_prospect(request: Request):
    data  = await request.json()
    phone = data.get("phone", "")
    if not phone:
        return {"ok": False, "error": "phone is required"}

    digits = re.sub(r"\D", "", phone)
    e164   = f"+{digits}" if digits.startswith("1") else f"+1{digits}"

    async with httpx.AsyncClient() as client:
        res = await client.post(
            "https://api.retellai.com/v2/create-phone-call",
            headers={
                "Authorization": f"Bearer {RETELL_API_KEY}",
                "Content-Type":  "application/json",
            },
            json={
                "from_number":       RETELL_FROM_NUMBER,
                "to_number":         e164,
                "override_agent_id": RETELL_AGENT_ID,
                "retell_llm_dynamic_variables": {
                    "prospect_name":    data.get("name",     "there"),
                    "listing_price":    data.get("price",    "your listing"),
                    "listing_location": data.get("location", "Austin"),
                },
                "metadata": {
                    "source":    "craigslist_fsbo",
                    "row_index": data.get("row_index"),
                },
            },
        )
    call_data = res.json()
    if not res.is_success:
        return {"ok": False, "error": call_data.get("message", str(call_data))}

    row_index = data.get("row_index")
    if row_index:
        service = _get_sheets_service()
        service.spreadsheets().values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=f"{PROSPECTS_SHEET_TAB}!K{row_index}",
            valueInputOption="USER_ENTERED",
            body={"values": [["Called"]]},
        ).execute()

    send_sms(AGENT_PHONE,
        f"📞 Ashley is calling FSBO prospect!\n"
        f"Name: {data.get('name','')}\nPhone: {e164}\n"
        f"Price: {data.get('price','')}\nLocation: {data.get('location','')}"
    )

    return {"ok": True, "call_id": call_data.get("call_id"), "to": e164}


@app.post("/mark_prospect")
async def mark_prospect(request: Request):
    data      = await request.json()
    row_index = data.get("row_index")
    status    = data.get("status", "")
    if not row_index or not status:
        return {"ok": False, "error": "row_index and status are required"}

    service = _get_sheets_service()
    service.spreadsheets().values().update(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{PROSPECTS_SHEET_TAB}!K{row_index}",
        valueInputOption="USER_ENTERED",
        body={"values": [[status]]},
    ).execute()
    return {"ok": True}


@app.get("/prospects")
def get_prospects():
    service = _get_sheets_service()
    result = service.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{PROSPECTS_SHEET_TAB}!A2:K"
    ).execute()
    rows = result.get("values", [])
    keys = ["date","title","price","location","phone","url","beds","baths","sqft","snippet","status"]
    return [dict(zip(keys, row)) for row in rows]
