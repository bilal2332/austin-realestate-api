from fastapi import FastAPI, Request
from google.oauth2 import service_account
from googleapiclient.discovery import build
from datetime import datetime, timedelta
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

def get_credentials():
    creds_json = os.environ.get("GOOGLE_CREDENTIALS_JSON")
    creds_dict = json.loads(creds_json)
    return service_account.Credentials.from_service_account_info(
        creds_dict, scopes=SCOPES
    )

def parse_money(value: str) -> int:
    """Convert any money format to integer. $2,000,000 / 2 million / two million → 2000000"""
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

@app.get("/")
def root():
    return {"status": "Austin RE Agent API is running"}

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

    return {"status": "success", "message": "Lead captured"}

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

        # Inject current year if missing
        if str(current_year) not in start_str:
            # Handle MM-DD or MM-DD format
            if "T" not in start_str and len(start_str) <= 10:
                start_str = f"{current_year}-{start_str}T10:00:00"
            elif "T" not in start_str:
                start_str = f"{current_year}-{start_str}T10:00:00"

        # Try full datetime format
        try:
            start_time = datetime.strptime(start_str, "%Y-%m-%dT%H:%M:%S")
        except ValueError:
            # Try date-only — default to 10am
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

    return {
        "status": "success",
        "message": f"Showing booked for {start_time.strftime('%B %d at %I:%M %p')}"
    }

@app.post("/search_listings")
async def search_listings(request: Request):
    data = await request.json()

    budget_raw = data.get("budget", "")
    area = data.get("area", "").lower().strip()
    beds_raw = data.get("beds", "")

    # Parse budget
    try:
        budget = parse_money(budget_raw)
    except Exception:
        budget = 99_999_999

    # Parse beds
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
        # Pad short rows
        while len(row) < len(headers):
            row.append("")

        listing = dict(zip(headers, row))

        # Skip unavailable
        if listing.get("Status", "").lower() != "available":
            continue

        # Parse listing price
        try:
            price = parse_money(listing.get("Price", "0"))
        except Exception:
            continue

        # Parse listing beds
        try:
            listing_beds = int(listing.get("Beds", "0"))
        except Exception:
            listing_beds = 0

        # Apply filters
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

    return {
        "status": "success",
        "count": len(top),
        "listings": top,
        "summary": " | ".join(summary)
    }
