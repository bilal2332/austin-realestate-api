from fastapi import FastAPI, Request
from google.oauth2 import service_account
from googleapiclient.discovery import build
from datetime import datetime, timedelta
from twilio.rest import Client
import httpx
import pytz
import os
import json

app = FastAPI()

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/calendar"
]

SPREADSHEET_ID = "1kdREpipKfSYCsj03csvG9brFYeQQu18Yxkp5DBRsPbo"
CALENDAR_ID = "chbilal.2332@gmail.com"
TIMEZONE = "America/Chicago"

# Twilio setup
TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN  = os.environ.get("TWILIO_AUTH_TOKEN")
TWILIO_PHONE       = os.environ.get("TWILIO_PHONE", "+17373345444")
AGENT_PHONE        = os.environ.get("AGENT_PHONE", "+17373345444")

twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

# Google Maps setup
GOOGLE_MAPS_API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY")

# Hardcoded Austin neighborhood data
NEIGHBORHOOD_DATA = {
    "south congress": {
        "vibe": "Trendy, artsy, walkable. Known for unique shops, live music, and restaurants.",
        "demographics": "Young professionals and creatives, ages 25-40.",
        "crime": "Low to moderate. Generally safe, busy streets.",
        "avg_price": "$620,000",
        "best_for": "First-time buyers who want walkable urban lifestyle."
    },
    "hyde park": {
        "vibe": "Quiet, historic, tree-lined streets. Very walkable near UT Austin.",
        "demographics": "Mix of students, professors, and established families.",
        "crime": "Low. One of Austin's safest central neighborhoods.",
        "avg_price": "$580,000",
        "best_for": "Families and academics who want charm and quiet."
    },
    "mueller": {
        "vibe": "Modern planned community, parks everywhere, very family friendly.",
        "demographics": "Young families and professionals, ages 30-45.",
        "crime": "Very low. Master-planned with security in mind.",
        "avg_price": "$550,000",
        "best_for": "Families wanting new construction and community feel."
    },
    "east austin": {
        "vibe": "Hip, eclectic, rapidly growing. Best food and bar scene in Austin.",
        "demographics": "Millennials, artists, young professionals.",
        "crime": "Moderate. Improving rapidly as area develops.",
        "avg_price": "$650,000",
        "best_for": "Buyers who want culture, nightlife, and investment potential."
    },
    "zilker": {
        "vibe": "Outdoor lover's paradise. Next to Barton Springs and Lady Bird Lake.",
        "demographics": "Active professionals and families, ages 28-45.",
        "crime": "Low. Very desirable area.",
        "avg_price": "$900,000",
        "best_for": "Outdoor enthusiasts who want a premium location."
    },
    "domain": {
        "vibe": "Upscale, tech hub, luxury shopping and dining. Austin's second downtown.",
        "demographics": "Tech workers, young professionals, transplants.",
        "crime": "Very low. Well-patrolled area.",
        "avg_price": "$480,000",
        "best_for": "Tech workers at Apple, Dell, Google wanting a short commute."
    },
    "brentwood": {
        "vibe": "Quiet, established, classic Austin neighborhood. Very residential.",
        "demographics": "Long-term Austin families and retirees.",
        "crime": "Very low. Tight-knit community.",
        "avg_price": "$700,000",
        "best_for": "Buyers wanting a stable neighborhood close to downtown."
    },
    "south lamar": {
        "vibe": "Vibrant, restaurant-heavy, great nightlife. Very Austin feel.",
        "demographics": "Young professionals and couples, ages 25-38.",
        "crime": "Low to moderate.",
        "avg_price": "$680,000",
        "best_for": "Buyers who love food, music, and Austin culture."
    },
    "cedar park": {
        "vibe": "Suburban, family-oriented, great schools, quieter pace.",
        "demographics": "Families with children, ages 30-50.",
        "crime": "Very low. One of the safest suburbs.",
        "avg_price": "$420,000",
        "best_for": "Families wanting space, top schools, and lower prices."
    },
    "round rock": {
        "vibe": "Large suburb, great for families, home of Dell headquarters.",
        "demographics": "Families and corporate workers.",
        "crime": "Very low.",
        "avg_price": "$390,000",
        "best_for": "Budget-conscious families wanting good schools and space."
    },
    "westlake": {
        "vibe": "Affluent, prestigious, rolling hills. Top-rated schools in Texas.",
        "demographics": "High-income families.",
        "crime": "Extremely low.",
        "avg_price": "$1,400,000",
        "best_for": "Luxury buyers wanting the best schools and exclusivity."
    },
    "travis heights": {
        "vibe": "Charming, hilly, eclectic. Walking distance to South Congress.",
        "demographics": "Artists, professionals, long-term Austinites.",
        "crime": "Low.",
        "avg_price": "$750,000",
        "best_for": "Buyers wanting character homes and walkable lifestyle."
    }
}


# ── Helpers ────────────────────────────────────────────────────────────────

def get_credentials():
    creds_json = os.environ.get("GOOGLE_CREDENTIALS_JSON")
    creds_dict = json.loads(creds_json)
    return service_account.Credentials.from_service_account_info(
        creds_dict, scopes=SCOPES
    )

def parse_money(value: str) -> int:
    v = str(value).lower().replace("$", "").replace(",", "").strip()
    word_map = {
        "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
        "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10
    }
    if "million" in v:
        num = v.replace("million", "").strip()
        num = word_map.get(num, float(num) if num else 1)
        return int(float(num) * 1_000_000)
    elif "thousand" in v or v.endswith("k"):
        num = v.replace("thousand", "").replace("k", "").strip()
        return int(float(num) * 1_000)
    else:
        return int(float(v.replace(" ", "")))

def send_sms(to: str, body: str):
    try:
        message = twilio_client.messages.create(
            body=body,
            from_=TWILIO_PHONE,
            to=to
        )
        print(f"SMS sent: {message.sid}")
    except Exception as e:
        print(f"SMS error: {e}")


# ── Health Check ───────────────────────────────────────────────────────────

@app.get("/")
def root():
    return {"status": "Austin RE Agent API is running"}


# ── Capture Lead ───────────────────────────────────────────────────────────

@app.post("/capture_lead")
async def capture_lead(request: Request):
    data = await request.json()

    creds = get_credentials()
    service = build("sheets", "v4", credentials=creds)

    row = [[
        datetime.now(pytz.timezone(TIMEZONE)).strftime("%Y-%m-%d %H:%M:%S"),
        data.get("name", ""),
        data.get("phone", ""),
        data.get("email", ""),
        data.get("intent", ""),
        data.get("budget", ""),
        data.get("timeline", ""),
        data.get("notes", "")
    ]]

    service.spreadsheets().values().append(
        spreadsheetId=SPREADSHEET_ID,
        range="Leads!A:H",
        valueInputOption="RAW",
        body={"values": row}
    ).execute()

    send_sms(
        to=AGENT_PHONE,
        body=(
            f"🏡 New Lead!\n"
            f"Name: {data.get('name', '')}\n"
            f"Phone: {data.get('phone', '')}\n"
            f"Budget: {data.get('budget', '')}\n"
            f"Intent: {data.get('intent', '')}\n"
            f"Timeline: {data.get('timeline', '')}"
        )
    )

    return {"status": "success", "message": "Lead captured"}


# ── Book Showing ───────────────────────────────────────────────────────────

@app.post("/book_showing")
async def book_showing(request: Request):
    data = await request.json()

    creds = get_credentials()
    cal_service = build("calendar", "v3", credentials=creds)

    tz = pytz.timezone(TIMEZONE)
    current_year = datetime.now(tz).year

    try:
        start_str = data.get("datetime", "").strip()

        if not start_str:
            return {
                "status": "error",
                "message": "I didn't receive a date. Could you please tell me what date and time works for you?"
            }

        if str(current_year) not in start_str:
            if "T" not in start_str and len(start_str) <= 10:
                start_str = f"{current_year}-{start_str}T10:00:00"
            elif "T" not in start_str:
                start_str = f"{current_year}-{start_str}T10:00:00"

        try:
            start_time = datetime.strptime(start_str, "%Y-%m-%dT%H:%M:%S")
        except ValueError:
            start_time = datetime.strptime(start_str, "%Y-%m-%d")
            start_time = start_time.replace(hour=10, minute=0, second=0)

        start_time = tz.localize(start_time)

    except Exception:
        return {
            "status": "error",
            "message": "I couldn't understand that date and time. Could you please repeat it? For example, April 13th at 2pm."
        }

    end_time = start_time + timedelta(hours=1)

    event = {
        "summary": f"Property Showing — {data.get('name', 'Prospect')}",
        "description": (
            f"Phone: {data.get('phone', '')}\n"
            f"Budget: {data.get('budget', '')}\n"
            f"Notes: {data.get('notes', '')}"
        ),
        "start": {"dateTime": start_time.isoformat(), "timeZone": TIMEZONE},
        "end": {"dateTime": end_time.isoformat(), "timeZone": TIMEZONE},
    }

    cal_service.events().insert(calendarId=CALENDAR_ID, body=event).execute()

    send_sms(
        to=AGENT_PHONE,
        body=(
            f"📅 Showing Booked!\n"
            f"Name: {data.get('name', '')}\n"
            f"Phone: {data.get('phone', '')}\n"
            f"Time: {start_time.strftime('%B %d at %I:%M %p')}\n"
            f"Budget: {data.get('budget', '')}\n"
            f"Notes: {data.get('notes', '')}"
        )
    )

    return {
        "status": "success",
        "message": f"Showing booked for {start_time.strftime('%B %d at %I:%M %p')}"
    }


# ── Search Listings ────────────────────────────────────────────────────────

@app.post("/search_listings")
async def search_listings(request: Request):
    data = await request.json()

    budget_raw = data.get("budget", "")
    area = data.get("area", "").lower().strip()
    beds_raw = data.get("beds", "")

    try:
        budget = parse_money(budget_raw)
    except Exception:
        budget = 99_999_999

    try:
        beds = int(str(beds_raw).strip())
    except Exception:
        beds = 0

    creds = get_credentials()
    service = build("sheets", "v4", credentials=creds)

    result = service.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID,
        range="Listings!A:I"
    ).execute()

    rows = result.get("values", [])
    if len(rows) <= 1:
        return {"status": "no_listings", "message": "No listings available right now."}

    headers = rows[0]
    listings = []

    for row in rows[1:]:
        while len(row) < len(headers):
            row.append("")

        listing = dict(zip(headers, row))

        if listing.get("Status", "").lower() != "available":
            continue

        try:
            price = parse_money(listing.get("Price", "0"))
        except Exception:
            continue

        try:
            listing_beds = int(listing.get("Beds", "0"))
        except Exception:
            listing_beds = 0

        if price > budget:
            continue
        if area and area not in listing.get("Area", "").lower():
            continue
        if beds and listing_beds < beds:
            continue

        listings.append({
            "address": listing.get("Address", ""),
            "area": listing.get("Area", ""),
            "price": listing.get("Price", ""),
            "beds": listing.get("Beds", ""),
            "baths": listing.get("Baths", ""),
            "sqft": listing.get("SqFt", ""),
            "notes": listing.get("Notes", "")
        })

    if not listings:
        return {
            "status": "no_match",
            "message": "No listings found matching those criteria."
        }

    top = listings[:3]
    summary = []
    for l in top:
        summary.append(
            f"{l['address']} in {l['area']} — {l['price']}, "
            f"{l['beds']} bed/{l['baths']} bath, {l['sqft']} sqft. {l['notes']}"
        )

    send_sms(
        to=AGENT_PHONE,
        body=(
            f"🔍 Listing Search!\n"
            f"Area: {area or 'Any'}\n"
            f"Budget: {budget_raw}\n"
            f"Beds: {beds_raw or 'Any'}\n"
            f"Matches found: {len(top)}"
        )
    )

    return {
        "status": "success",
        "count": len(top),
        "listings": top,
        "summary": " | ".join(summary)
    }


# ── Neighborhood Intel ─────────────────────────────────────────────────────

@app.post("/neighborhood_intel")
async def neighborhood_intel(request: Request):
    data = await request.json()
    neighborhood = data.get("neighborhood", "").lower().strip()

    matched = None
    for key in NEIGHBORHOOD_DATA:
        if key in neighborhood or neighborhood in key:
            matched = key
            break

    if not matched:
        available = ", ".join([n.title() for n in NEIGHBORHOOD_DATA.keys()])
        return {
            "status": "not_found",
            "message": f"I don't have data for that neighborhood yet. I currently cover: {available}."
        }

    info = NEIGHBORHOOD_DATA[matched]

    # Get commute time to downtown Austin
    commute_text = "unavailable"
    try:
        origin = f"{matched.replace(' ', '+')}+Austin+TX"
        destination = "Downtown+Austin+TX"
        maps_url = (
            f"https://maps.googleapis.com/maps/api/distancematrix/json"
            f"?origins={origin}&destinations={destination}"
            f"&mode=driving&key={GOOGLE_MAPS_API_KEY}"
        )
        async with httpx.AsyncClient() as client:
            resp = await client.get(maps_url)
            maps_data = resp.json()
            commute_text = maps_data["rows"][0]["elements"][0]["duration"]["text"]
    except Exception as e:
        print(f"Maps API error: {e}")

    # Get nearby restaurants
    nearby_text = "unavailable"
    try:
        places_url = (
            f"https://maps.googleapis.com/maps/api/place/textsearch/json"
            f"?query=restaurants+in+{matched.replace(' ', '+')}+Austin+TX"
            f"&key={GOOGLE_MAPS_API_KEY}"
        )
        async with httpx.AsyncClient() as client:
            resp = await client.get(places_url)
            places_data = resp.json()
            results = places_data.get("results", [])[:3]
            if results:
                names = [r["name"] for r in results]
                nearby_text = ", ".join(names)
    except Exception as e:
        print(f"Places API error: {e}")

    summary = (
        f"{matched.title()} neighborhood: {info['vibe']} "
        f"Average home price is {info['avg_price']}. "
        f"Crime level: {info['crime']} "
        f"Residents: {info['demographics']} "
        f"Drive to downtown Austin: {commute_text}. "
        f"Popular nearby spots: {nearby_text}. "
        f"Best for: {info['best_for']}"
    )

    return {
        "status": "success",
        "neighborhood": matched.title(),
        "avg_price": info["avg_price"],
        "vibe": info["vibe"],
        "crime": info["crime"],
        "demographics": info["demographics"],
        "commute_to_downtown": commute_text,
        "nearby_restaurants": nearby_text,
        "best_for": info["best_for"],
        "summary": summary
    }
