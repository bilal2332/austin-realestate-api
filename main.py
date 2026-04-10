from fastapi import FastAPI, Request
from google.oauth2 import service_account
from googleapiclient.discovery import build
from datetime import datetime, timedelta
import pytz
import os

app = FastAPI()

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/calendar"
]

SPREADSHEET_ID = "1kdREpipKfSYCsj03csvG9brFYeQQu18Yxkp5DBRsPbo"
CALENDAR_ID = "chbilal.2332@gmail.com"
TIMEZONE = "America/Chicago"

def get_credentials():
    return service_account.Credentials.from_service_account_file(
        "credentials.json", scopes=SCOPES
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
    sheets_service = build("sheets", "v4", credentials=creds)
    
    # Parse date/time — default to tomorrow 10am if not provided
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
    
    # Also log as lead
    row = [[
        datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S"),
        data.get("name", ""),
        data.get("phone", ""),
        data.get("email", ""),
        "buying",
        data.get("budget", ""),
        data.get("timeline", ""),
        f"Showing booked: {start_time.strftime('%b %d at %I:%M %p')}"
    ]]
    
    sheets_service.spreadsheets().values().append(
        spreadsheetId=SPREADSHEET_ID,
        range="Leads!A:H",
        valueInputOption="RAW",
        body={"values": row}
    ).execute()
    
    return {
        "status": "success",
        "message": f"Showing booked for {start_time.strftime('%B %d at %I:%M %p')}"
    }
