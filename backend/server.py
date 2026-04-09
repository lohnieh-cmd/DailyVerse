from fastapi import FastAPI, APIRouter, HTTPException, UploadFile, File
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from pathlib import Path
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime, date
from bson import ObjectId
import httpx
import io

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ.get('DB_NAME', 'scripture_app')]

# Create the main app
app = FastAPI(title="Daily Scripture Verse API")

# Create a router with the /api prefix
api_router = APIRouter(prefix="/api")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Helper to convert ObjectId to string
def serialize_doc(doc):
    if doc:
        doc['_id'] = str(doc['_id'])
    return doc

# ==================== MODELS ====================

class VerseCreate(BaseModel):
    reference: str
    text: Optional[str] = None  # Optional - will be fetched from API if not provided
    audio_base64: Optional[str] = None

class VerseUpdate(BaseModel):
    reference: Optional[str] = None
    text: Optional[str] = None
    audio_base64: Optional[str] = None

class VerseResponse(BaseModel):
    id: str = Field(alias='_id')
    reference: str
    text: str
    audio_base64: Optional[str] = None
    order: int
    date_added: datetime
    
    class Config:
        populate_by_name = True

class SettingsUpdate(BaseModel):
    notification_time: Optional[str] = None
    notification_enabled: Optional[bool] = None

class TodayVerseResponse(BaseModel):
    id: str
    reference: str
    text: str
    audio_base64: Optional[str] = None
    verse_number: int
    total_verses: int
    date: str
    is_holiday: bool = False
    holiday_name: Optional[str] = None
    is_weekend: bool = False

# ==================== BIBLE API ====================

# Afrikaans to English book name mapping
AFRIKAANS_BOOKS = {
    # Old Testament
    "gen": "genesis", "eks": "exodus", "exodus": "exodus", "lev": "leviticus", 
    "num": "numbers", "deut": "deuteronomy", "jos": "joshua", "rig": "judges", 
    "rut": "ruth", "1 sam": "1 samuel", "2 sam": "2 samuel", 
    "1 kon": "1 kings", "2 kon": "2 kings", "1 kron": "1 chronicles", 
    "2 kron": "2 chronicles", "2 chro": "2 chronicles", "1 chro": "1 chronicles",
    "esra": "ezra", "neh": "nehemiah", "est": "esther", "job": "job", 
    "ps": "psalms", "psalm": "psalms", "psalms": "psalms",
    "spr": "proverbs", "prov": "proverbs", "proverbs": "proverbs",
    "pred": "ecclesiastes", "hgl": "song of solomon",
    "jes": "isaiah", "isaiah": "isaiah", "jer": "jeremiah", "jeremiah": "jeremiah",
    "klaagl": "lamentations", "eseg": "ezekiel", "dan": "daniel", 
    "hos": "hosea", "joel": "joel", "amos": "amos", "ob": "obadiah", 
    "jona": "jonah", "mig": "micah", "nah": "nahum", "hab": "habakkuk", 
    "habakkuk": "habakkuk", "sef": "zephaniah", "hag": "haggai", 
    "sag": "zechariah", "mal": "malachi",
    # New Testament
    "matt": "matthew", "matthew": "matthew", "mark": "mark", 
    "luk": "luke", "luke": "luke", "joh": "john", "john": "john",
    "hand": "acts", "rom": "romans", "romans": "romans",
    "1 kor": "1 corinthians", "2 kor": "2 corinthians", 
    "1 cor": "1 corinthians", "2 cor": "2 corinthians",
    "gal": "galatians", "galatians": "galatians",
    "efe": "ephesians", "ephesians": "ephesians", "eph": "ephesians",
    "fil": "philippians", "phil": "philippians", "philippians": "philippians",
    "kol": "colossians", "col": "colossians", "colossians": "colossians",
    "1 tes": "1 thessalonians", "2 tes": "2 thessalonians",
    "1 tim": "1 timothy", "2 tim": "2 timothy", "timothy": "timothy",
    "tit": "titus", "filem": "philemon", "heb": "hebrews", "hebrews": "hebrews",
    "jak": "james", "james": "james",
    "1 pet": "1 peter", "2 pet": "2 peter", "1 peter": "1 peter", "2 peter": "2 peter",
    "1 joh": "1 john", "2 joh": "2 john", "3 joh": "3 john",
    "1 john": "1 john", "2 john": "2 john", "3 john": "3 john",
    "jud": "jude", "op": "revelation",
}

def convert_reference_to_english(reference: str) -> str:
    """Convert Afrikaans/abbreviated book names to English for Bible API"""
    import re
    
    ref = reference.strip()
    
    # Handle "Fil4:19" format (no space between book and chapter)
    match = re.match(r'^(\d?\s?[a-zA-Z]+)(\d+:\d+(?:-\d+)?)$', ref)
    if match:
        book_part = match.group(1).strip().lower()
        verse_part = match.group(2)
        
        for afr, eng in sorted(AFRIKAANS_BOOKS.items(), key=lambda x: -len(x[0])):
            if book_part == afr:
                return f"{eng} {verse_part}"
        return f"{book_part} {verse_part}"
    
    # Handle normal format "Book Chapter:Verse"
    match = re.match(r'^(\d?\s?[a-zA-Z]+)\s+(\d+:\d+(?:-\d+)?)$', ref)
    if match:
        book_part = match.group(1).strip().lower()
        verse_part = match.group(2)
        
        for afr, eng in sorted(AFRIKAANS_BOOKS.items(), key=lambda x: -len(x[0])):
            if book_part == afr:
                return f"{eng} {verse_part}"
        return f"{book_part} {verse_part}"
    
    return ref

async def fetch_verse_from_api(reference: str) -> str:
    """Fetch verse text from bible-api.com"""
    # Convert Afrikaans reference to English
    english_ref = convert_reference_to_english(reference)
    
    # Convert reference format: "Numbers 6:24-26" -> "numbers+6:24-26"
    formatted_ref = english_ref.lower().replace(" ", "+")
    
    url = f"https://bible-api.com/{formatted_ref}"
    logger.info(f"Fetching: {url} (original: {reference})")
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, timeout=15.0)
            if response.status_code == 200:
                data = response.json()
                text = data.get('text', '').strip()
                if text:
                    return text
                logger.warning(f"Empty text from Bible API for {reference}")
                return None
            else:
                logger.warning(f"Bible API returned {response.status_code} for {reference} (url: {url})")
                return None
        except Exception as e:
            logger.error(f"Error fetching verse {reference}: {e}")
            return None

# ==================== HOLIDAY API ====================

async def fetch_sa_holidays(year: int) -> List[dict]:
    """Fetch South African public holidays from Nager.Date API"""
    url = f"https://date.nager.at/api/v3/PublicHolidays/{year}/ZA"
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, timeout=10.0)
            if response.status_code == 200:
                holidays = response.json()
                return [{
                    'date': h['date'],
                    'name': h['localName']
                } for h in holidays]
            else:
                logger.warning(f"Holiday API returned {response.status_code}")
                return []
        except Exception as e:
            logger.error(f"Error fetching holidays: {e}")
            return []

def is_weekend(check_date: date) -> bool:
    """Check if date is Saturday (5) or Sunday (6)"""
    return check_date.weekday() >= 5

async def is_holiday(check_date: date, holidays: List[dict]) -> tuple:
    """Check if date is a South African public holiday"""
    date_str = check_date.isoformat()
    for h in holidays:
        if h['date'] == date_str:
            return True, h['name']
    return False, None

async def count_working_days_until(target_date: date, holidays: List[dict]) -> int:
    """Count working days from Jan 1 of the year until target_date (inclusive)"""
    year_start = date(target_date.year, 1, 1)
    working_days = 0
    current = year_start
    
    while current <= target_date:
        if not is_weekend(current):
            is_hol, _ = await is_holiday(current, holidays)
            if not is_hol:
                working_days += 1
        current = date(current.year, current.month, current.day + 1) if current.day < 28 else None
        if current is None:
            # Handle month overflow
            from datetime import timedelta
            current = target_date - timedelta(days=(target_date - year_start).days - working_days)
            break
    
    # Recalculate properly
    from datetime import timedelta
    working_days = 0
    current = year_start
    while current <= target_date:
        if not is_weekend(current):
            is_hol, _ = await is_holiday(current, holidays)
            if not is_hol:
                working_days += 1
        current = current + timedelta(days=1)
    
    return working_days

# ==================== VERSES ENDPOINTS ====================

@api_router.get("/")
async def root():
    return {"message": "Daily Scripture Verse API", "version": "1.0"}

@api_router.get("/verses", response_model=List[dict])
async def get_verses():
    """Get all verses ordered by position"""
    verses = await db.verses.find().sort("order", 1).to_list(1000)
    return [serialize_doc(v) for v in verses]

@api_router.post("/verses")
async def create_verse(verse: VerseCreate):
    """Add a new verse - auto-fetches text from Bible API if not provided"""
    # Get the next order number
    last_verse = await db.verses.find_one(sort=[("order", -1)])
    next_order = (last_verse['order'] + 1) if last_verse else 1
    
    # Fetch verse text if not provided
    text = verse.text
    if not text:
        text = await fetch_verse_from_api(verse.reference)
        if not text:
            raise HTTPException(status_code=400, detail=f"Could not fetch verse text for '{verse.reference}'. Please provide text manually.")
    
    verse_doc = {
        "reference": verse.reference,
        "text": text,
        "audio_base64": verse.audio_base64,
        "order": next_order,
        "date_added": datetime.utcnow()
    }
    
    result = await db.verses.insert_one(verse_doc)
    verse_doc['_id'] = str(result.inserted_id)
    
    return verse_doc

@api_router.put("/verses/{verse_id}")
async def update_verse(verse_id: str, verse: VerseUpdate):
    """Update an existing verse"""
    try:
        obj_id = ObjectId(verse_id)
    except:
        raise HTTPException(status_code=400, detail="Invalid verse ID")
    
    update_data = {k: v for k, v in verse.dict().items() if v is not None}
    
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")
    
    result = await db.verses.update_one(
        {"_id": obj_id},
        {"$set": update_data}
    )
    
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Verse not found")
    
    updated = await db.verses.find_one({"_id": obj_id})
    return serialize_doc(updated)

@api_router.delete("/verses/{verse_id}")
async def delete_verse(verse_id: str):
    """Delete a verse and reorder remaining verses"""
    try:
        obj_id = ObjectId(verse_id)
    except:
        raise HTTPException(status_code=400, detail="Invalid verse ID")
    
    # Get the verse to find its order
    verse = await db.verses.find_one({"_id": obj_id})
    if not verse:
        raise HTTPException(status_code=404, detail="Verse not found")
    
    deleted_order = verse['order']
    
    # Delete the verse
    await db.verses.delete_one({"_id": obj_id})
    
    # Reorder verses after the deleted one
    await db.verses.update_many(
        {"order": {"$gt": deleted_order}},
        {"$inc": {"order": -1}}
    )
    
    return {"message": "Verse deleted successfully"}

@api_router.post("/verses/reorder")
async def reorder_verses(verse_ids: List[str]):
    """Reorder verses based on provided ID list"""
    for idx, vid in enumerate(verse_ids, start=1):
        try:
            obj_id = ObjectId(vid)
            await db.verses.update_one(
                {"_id": obj_id},
                {"$set": {"order": idx}}
            )
        except Exception as e:
            logger.error(f"Error reordering verse {vid}: {e}")
    
    return {"message": "Verses reordered successfully"}

# ==================== TODAY'S VERSE ====================

@api_router.get("/verse/today")
async def get_today_verse():
    """Get the verse for today based on working days calculation"""
    today = date.today()
    
    # Fetch holidays for this year
    holidays = await fetch_sa_holidays(today.year)
    
    # Check if today is a weekend
    if is_weekend(today):
        return {
            "message": "No verse today - it's the weekend!",
            "is_weekend": True,
            "is_holiday": False,
            "date": today.isoformat()
        }
    
    # Check if today is a holiday
    is_hol, holiday_name = await is_holiday(today, holidays)
    if is_hol:
        return {
            "message": f"No verse today - it's {holiday_name}!",
            "is_weekend": False,
            "is_holiday": True,
            "holiday_name": holiday_name,
            "date": today.isoformat()
        }
    
    # Count working days this year
    working_day_num = await count_working_days_until(today, holidays)
    
    # Get total verses
    total_verses = await db.verses.count_documents({})
    
    if total_verses == 0:
        return {
            "message": "No verses in database. Please add some verses first.",
            "is_weekend": False,
            "is_holiday": False,
            "date": today.isoformat()
        }
    
    # Calculate which verse to show (cycle through list)
    verse_index = ((working_day_num - 1) % total_verses) + 1
    
    # Get the verse at this position
    verse = await db.verses.find_one({"order": verse_index})
    
    if not verse:
        # Fallback to first verse if order mismatch
        verse = await db.verses.find_one(sort=[("order", 1)])
    
    return {
        "id": str(verse['_id']),
        "reference": verse['reference'],
        "text": verse['text'],
        "audio_base64": verse.get('audio_base64'),
        "verse_number": verse_index,
        "total_verses": total_verses,
        "working_day_of_year": working_day_num,
        "date": today.isoformat(),
        "is_weekend": False,
        "is_holiday": False
    }

# ==================== HOLIDAYS ====================

@api_router.get("/holidays/{year}")
async def get_holidays(year: int):
    """Get South African public holidays for a specific year"""
    holidays = await fetch_sa_holidays(year)
    return {"year": year, "country": "South Africa", "holidays": holidays}

# ==================== SETTINGS ====================

@api_router.get("/settings")
async def get_settings():
    """Get app settings"""
    settings = await db.settings.find_one({"type": "user_settings"})
    if not settings:
        # Create default settings
        default_settings = {
            "type": "user_settings",
            "notification_time": "07:00",
            "notification_enabled": True
        }
        result = await db.settings.insert_one(default_settings)
        default_settings['_id'] = str(result.inserted_id)
        return default_settings
    return serialize_doc(settings)

@api_router.put("/settings")
async def update_settings(settings: SettingsUpdate):
    """Update app settings"""
    update_data = {k: v for k, v in settings.dict().items() if v is not None}
    
    result = await db.settings.update_one(
        {"type": "user_settings"},
        {"$set": update_data},
        upsert=True
    )
    
    updated = await db.settings.find_one({"type": "user_settings"})
    return serialize_doc(updated)

# ==================== EXCEL IMPORT ====================

@api_router.post("/import/excel")
async def import_excel(file: UploadFile = File(...)):
    """Import verses from an Excel file. Column A should have verse references."""
    import openpyxl
    
    if not file.filename.endswith(('.xlsx', '.xls')):
        raise HTTPException(status_code=400, detail="Please upload an Excel file (.xlsx or .xls)")
    
    try:
        contents = await file.read()
        workbook = openpyxl.load_workbook(io.BytesIO(contents))
        sheet = workbook.active
        
        # Get the next order number
        last_verse = await db.verses.find_one(sort=[("order", -1)])
        next_order = (last_verse['order'] + 1) if last_verse else 1
        
        imported_count = 0
        failed_refs = []
        
        for row in sheet.iter_rows(min_row=1, max_col=2, values_only=True):
            reference = row[0]
            provided_text = row[1] if len(row) > 1 else None
            
            if not reference or str(reference).strip() == '':
                continue
            
            reference = str(reference).strip()
            
            # Check if verse already exists
            existing = await db.verses.find_one({"reference": reference})
            if existing:
                continue
            
            # Get verse text
            text = str(provided_text).strip() if provided_text else None
            if not text:
                text = await fetch_verse_from_api(reference)
            
            if not text:
                failed_refs.append(reference)
                continue
            
            verse_doc = {
                "reference": reference,
                "text": text,
                "audio_base64": None,
                "order": next_order,
                "date_added": datetime.utcnow()
            }
            
            await db.verses.insert_one(verse_doc)
            next_order += 1
            imported_count += 1
        
        return {
            "message": f"Successfully imported {imported_count} verses",
            "imported_count": imported_count,
            "failed_references": failed_refs
        }
        
    except Exception as e:
        logger.error(f"Error importing Excel: {e}")
        raise HTTPException(status_code=500, detail=f"Error processing Excel file: {str(e)}")

# ==================== SEED DATA ====================

@api_router.post("/seed")
async def seed_sample_verses():
    """Seed database with sample verses for testing"""
    sample_verses = [
        "Numbers 6:24-26",
        "Job 33:4",
        "2 Peter 1:20-21",
        "Psalm 23:1-3",
        "John 3:16",
        "Romans 8:28",
        "Philippians 4:13",
        "Jeremiah 29:11",
        "Proverbs 3:5-6",
        "Isaiah 41:10"
    ]
    
    # Check if already seeded
    existing = await db.verses.count_documents({})
    if existing > 0:
        return {"message": f"Database already has {existing} verses. Clear first if you want to reseed."}
    
    imported_count = 0
    failed_refs = []
    
    for idx, reference in enumerate(sample_verses, start=1):
        text = await fetch_verse_from_api(reference)
        
        if not text:
            failed_refs.append(reference)
            continue
        
        verse_doc = {
            "reference": reference,
            "text": text,
            "audio_base64": None,
            "order": idx,
            "date_added": datetime.utcnow()
        }
        
        await db.verses.insert_one(verse_doc)
        imported_count += 1
    
    return {
        "message": f"Seeded {imported_count} sample verses",
        "imported_count": imported_count,
        "failed_references": failed_refs
    }

@api_router.delete("/verses")
async def clear_all_verses():
    """Clear all verses from database"""
    result = await db.verses.delete_many({})
    return {"message": f"Deleted {result.deleted_count} verses"}

class BulkVerseImport(BaseModel):
    references: List[str]

@api_router.post("/import/bulk")
async def import_bulk_verses(data: BulkVerseImport):
    """Import multiple verses by reference - auto-fetches text from Bible API"""
    import asyncio
    
    # Get the next order number
    last_verse = await db.verses.find_one(sort=[("order", -1)])
    next_order = (last_verse['order'] + 1) if last_verse else 1
    
    imported_count = 0
    failed_refs = []
    skipped_refs = []
    
    for reference in data.references:
        reference = reference.strip()
        if not reference:
            continue
        
        # Check if verse already exists
        existing = await db.verses.find_one({"reference": reference})
        if existing:
            skipped_refs.append(reference)
            continue
        
        # Fetch verse text with retry and rate limiting
        text = None
        for attempt in range(3):
            text = await fetch_verse_from_api(reference)
            if text:
                break
            # Wait before retry (exponential backoff)
            await asyncio.sleep(1 * (attempt + 1))
        
        if not text:
            failed_refs.append(reference)
            continue
        
        verse_doc = {
            "reference": reference,
            "text": text,
            "audio_base64": None,
            "order": next_order,
            "date_added": datetime.utcnow()
        }
        
        await db.verses.insert_one(verse_doc)
        next_order += 1
        imported_count += 1
        logger.info(f"Imported verse: {reference}")
        
        # Rate limiting: wait 500ms between successful requests
        await asyncio.sleep(0.5)
    
    return {
        "message": f"Successfully imported {imported_count} verses",
        "imported_count": imported_count,
        "skipped_count": len(skipped_refs),
        "failed_references": failed_refs,
        "skipped_references": skipped_refs
    }

# Include the router in the main app
app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
