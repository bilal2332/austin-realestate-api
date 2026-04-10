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
    try:
        start_str = data.get("datetime", "")
        start_time = datetime.strptime(start_str, "%Y-%m-%dT%H:%M:%S")
        start_time = tz.localize(start_time)
    except:
        tomorrow = datetime.now(tz) + timedelta(days=1)
        start_time = tomorrow.replace(hour=10, minute=0, second=0, microsecond=0)

    end_time = start_time + timedelta(hours=1)

    event = {
        "summary": f"Property Showing — {data.get('name', 'Prospect')}",
        "description": f"Phone: {data.get('phone', '')}\nBudget: {data.get('budget', '')}\nNotes: {data.get('notes', '')}",
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

    # Parse budget — strip $, commas, convert to int
    try:
        budget = int(str(budget_raw).replace("$", "").replace(",", "").replace(" ", ""))
    except:
        budget = 99999999

    # Parse beds
    try:
        beds = int(str(beds_raw).strip())
    except:
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
            price = int(str(listing.get("Price", "0")).replace("$", "").replace(",", "").replace(" ", ""))
        except:
            continue

        # Parse listing beds
        try:
            listing_beds = int(listing.get("Beds", "0"))
        except:
            listing_beds = 0

        # Filter by budget
        if price > budget:
            continue

        # Filter by area if provided
        if area and area not in listing.get("Area", "").lower():
            continue

        # Filter by beds if provided
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

    # Return top 3 matches
    top = listings[:3]
    summary = []
    for l in top:
        summary.append(
            f"{l['address']} in {l['area']} — {l['price']}, {l['beds']} bed/{l['baths']} bath, {l['sqft']} sqft. {l['notes']}"
        )

    return {
        "status": "success",
        "count": len(top),
        "listings": top,
        "summary": " | ".join(summary)
    }
