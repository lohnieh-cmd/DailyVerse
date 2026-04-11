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
import re
from bs4 import BeautifulSoup

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
    text: str  # Required - must be provided in exact translation
    translation: Optional[str] = None  # e.g., "AFR53", "NIV", "NLV"
    language: Optional[str] = None  # e.g., "Afr", "Eng"
    audio_base64: Optional[str] = None

class VerseUpdate(BaseModel):
    reference: Optional[str] = None
    text: Optional[str] = None
    translation: Optional[str] = None
    language: Optional[str] = None
    audio_base64: Optional[str] = None

class VerseResponse(BaseModel):
    id: str = Field(alias='_id')
    reference: str
    text: str
    translation: Optional[str] = None
    language: Optional[str] = None
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
    translation: Optional[str] = None
    language: Optional[str] = None
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

async def fetch_verse_from_bible_com(url: str) -> str:
    """
    Fetch verse text from Bible.com URL.
    Supports both direct verse URLs and search URLs.
    
    Direct URL format: https://www.bible.com/bible/117/MAT.21.22.NLV
    Search URL format: https://www.bible.com/search/bible?query=Matt%2021:22%20NLV
    """
    if not url or not url.strip():
        return None
    
    url = url.strip()
    
    # Make sure it's a bible.com URL
    if 'bible.com' not in url:
        logger.warning(f"Not a Bible.com URL: {url}")
        return None
    
    # Convert search URL to direct URL for better results
    if '/search/' in url:
        direct_url = convert_search_url_to_direct(url)
        if direct_url:
            logger.info(f"Converted search URL to direct: {direct_url}")
            url = direct_url
    
    async with httpx.AsyncClient() as client:
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            response = await client.get(url, headers=headers, timeout=15.0, follow_redirects=True)
            
            if response.status_code != 200:
                logger.warning(f"Bible.com returned {response.status_code} for {url}")
                return None
            
            html = response.text
            soup = BeautifulSoup(html, 'html.parser')
            
            # Method 1: Look for meta description (usually contains the verse)
            meta_desc = soup.find('meta', {'name': 'description'})
            if meta_desc and meta_desc.get('content'):
                verse_text = meta_desc['content'].strip()
                # Skip if it's just search results text
                if verse_text and len(verse_text) > 10 and not verse_text.startswith('Search results'):
                    logger.info(f"Found verse from meta description: {verse_text[:50]}...")
                    return verse_text
            
            # Method 2: Look for og:description
            og_desc = soup.find('meta', {'property': 'og:description'})
            if og_desc and og_desc.get('content'):
                verse_text = og_desc['content'].strip()
                if verse_text and len(verse_text) > 10 and not verse_text.startswith('Search results'):
                    logger.info(f"Found verse from og:description: {verse_text[:50]}...")
                    return verse_text
            
            # Method 3: For search pages, try to find the first verse result
            # Look for verse content in search results
            verse_links = soup.find_all('a', href=lambda x: x and '/bible/' in x and not '/compare/' in x)
            for link in verse_links[:3]:  # Check first 3 links
                verse_text_elem = link.find_next(['p', 'div', 'span'])
                if verse_text_elem:
                    text = verse_text_elem.get_text(strip=True)
                    if text and len(text) > 20 and len(text) < 2000:
                        # Clean up
                        text = re.sub(r'Read\s+\w+.*$', '', text, flags=re.IGNORECASE).strip()
                        if text:
                            logger.info(f"Found verse from search result: {text[:50]}...")
                            return text
            
            # Method 4: Look for any substantial text content
            for tag in ['p', 'div', 'span']:
                elements = soup.find_all(tag)
                for elem in elements:
                    text = elem.get_text(strip=True)
                    # Look for text that looks like a verse (has some punctuation, reasonable length)
                    if text and 30 < len(text) < 1000 and ('.' in text or ',' in text):
                        # Skip navigation/UI text
                        if any(skip in text.lower() for skip in ['search', 'download', 'sign in', 'cookie', 'privacy']):
                            continue
                        logger.info(f"Found verse from content: {text[:50]}...")
                        return text
            
            logger.warning(f"Could not extract verse text from {url}")
            return None
            
        except Exception as e:
            logger.error(f"Error fetching verse from Bible.com {url}: {e}")
            return None

def convert_search_url_to_direct(search_url: str) -> str:
    """
    Convert a Bible.com search URL to a direct verse URL.
    
    Search: https://www.bible.com/search/bible?query=Matt%2021:22%20NLV
    Direct: https://www.bible.com/bible/117/MAT.21.22.NLV
    """
    import urllib.parse
    
    try:
        # Parse the URL
        parsed = urllib.parse.urlparse(search_url)
        query_params = urllib.parse.parse_qs(parsed.query)
        
        if 'query' not in query_params:
            return None
        
        query = urllib.parse.unquote(query_params['query'][0]).strip()
        
        # Parse the query: "Matt 21:22 NLV" or "Jes 53:5 AFR53"
        parts = query.split()
        if len(parts) < 2:
            return None
        
        translation = parts[-1].upper()  # Last part is translation
        verse_ref = ' '.join(parts[:-1])  # Everything else is verse reference
        
        # Get Bible ID for translation
        bible_ids = {
            'NLV': 117,    # Nuwe Lewende Vertaling
            'AFR53': 5,    # Afrikaans 1933/53
            'AFR83': 6,    # Afrikaans 1983 (CORRECTED - was 36)
            'NIV': 111,    # New International Version
            'KJV': 1,      # King James Version
            'ESV': 59,     # English Standard Version
            'NLT': 116,    # New Living Translation
            'NKJV': 114,   # New King James Version
            'MSG': 97,     # The Message
            'AMP': 8,      # Amplified Bible
            'DB': 143,     # Die Boodskap (Afrikaans)
        }
        
        bible_id = bible_ids.get(translation)
        if not bible_id:
            logger.warning(f"Unknown translation: {translation}")
            return None
        
        # Parse verse reference: "Matt 21:22" or "1 Kor 13:4-8" or "Fil4:19"
        # Handle cases like "Fil4:19" (no space)
        match = re.match(r'^(\d?\s?[A-Za-z]+)\s*(\d+):(\d+(?:-\d+)?)$', verse_ref)
        if not match:
            logger.warning(f"Could not parse verse reference: {verse_ref}")
            return None
        
        book_name = match.group(1).strip()
        chapter = match.group(2)
        verse = match.group(3)
        
        # Convert book name to Bible.com format
        book_codes = {
            # Afrikaans book names
            'matt': 'MAT', 'matteus': 'MAT',
            'mark': 'MRK', 'markus': 'MRK',
            'luk': 'LUK', 'lukas': 'LUK',
            'joh': 'JHN', 'johannes': 'JHN',
            'hand': 'ACT', 'handelinge': 'ACT',
            'rom': 'ROM', 'romeine': 'ROM',
            '1 kor': '1CO', '1kor': '1CO', '1 korintiërs': '1CO',
            '2 kor': '2CO', '2kor': '2CO', '2 korintiërs': '2CO',
            'gal': 'GAL', 'galasiërs': 'GAL',
            'efe': 'EPH', 'efesiërs': 'EPH',
            'fil': 'PHP', 'filippense': 'PHP',
            'kol': 'COL', 'kolossense': 'COL',
            '1 tes': '1TH', '1tes': '1TH',
            '2 tes': '2TH', '2tes': '2TH',
            '1 tim': '1TI', '1tim': '1TI',
            '2 tim': '2TI', '2tim': '2TI',
            'tit': 'TIT', 'titus': 'TIT',
            'filem': 'PHM', 'filemon': 'PHM',
            'heb': 'HEB', 'hebreërs': 'HEB',
            'jak': 'JAS', 'jakobus': 'JAS',
            '1 pet': '1PE', '1pet': '1PE',
            '2 pet': '2PE', '2pet': '2PE',
            '1 joh': '1JN', '1joh': '1JN',
            '2 joh': '2JN', '2joh': '2JN',
            '3 joh': '3JN', '3joh': '3JN',
            'jud': 'JUD', 'judas': 'JUD',
            'op': 'REV', 'openbaring': 'REV',
            # Old Testament
            'gen': 'GEN', 'genesis': 'GEN',
            'eks': 'EXO', 'exodus': 'EXO',
            'lev': 'LEV', 'levitikus': 'LEV',
            'num': 'NUM', 'numeri': 'NUM',
            'deut': 'DEU', 'deuteronomium': 'DEU',
            'jos': 'JOS', 'josua': 'JOS',
            'rig': 'JDG', 'rigters': 'JDG',
            'rut': 'RUT', 'ruth': 'RUT',
            '1 sam': '1SA', '1sam': '1SA',
            '2 sam': '2SA', '2sam': '2SA',
            '1 kon': '1KI', '1kon': '1KI',
            '2 kon': '2KI', '2kon': '2KI',
            '1 kron': '1CH', '1kron': '1CH',
            '2 kron': '2CH', '2kron': '2CH',
            'esra': 'EZR',
            'neh': 'NEH', 'nehemia': 'NEH',
            'est': 'EST', 'ester': 'EST',
            'job': 'JOB',
            'ps': 'PSA', 'psalm': 'PSA', 'psalms': 'PSA',
            'spr': 'PRO', 'spreuke': 'PRO',
            'pred': 'ECC', 'prediker': 'ECC',
            'hgl': 'SNG', 'hooglied': 'SNG',
            'jes': 'ISA', 'jesaja': 'ISA',
            'jer': 'JER', 'jeremia': 'JER',
            'klaagl': 'LAM', 'klaagliedere': 'LAM',
            'eseg': 'EZK', 'esegiël': 'EZK',
            'dan': 'DAN', 'daniël': 'DAN',
            'hos': 'HOS', 'hosea': 'HOS',
            'joel': 'JOL', 'joël': 'JOL',
            'amos': 'AMO',
            'ob': 'OBA', 'obadja': 'OBA',
            'jona': 'JON',
            'mig': 'MIC', 'miga': 'MIC',
            'nah': 'NAM', 'nahum': 'NAM',
            'hab': 'HAB', 'habakuk': 'HAB',
            'sef': 'ZEP', 'sefanja': 'ZEP',
            'hag': 'HAG', 'haggai': 'HAG',
            'sag': 'ZEC', 'sagaria': 'ZEC',
            'mal': 'MAL', 'maleagi': 'MAL',
            # English variations
            'matthew': 'MAT', 'luke': 'LUK', 'john': 'JHN',
            'acts': 'ACT', 'romans': 'ROM',
            '1 cor': '1CO', '2 cor': '2CO',
            'galatians': 'GAL', 'ephesians': 'EPH',
            'phil': 'PHP', 'philippians': 'PHP',
            'col': 'COL', 'colossians': 'COL',
            '1 thess': '1TH', '2 thess': '2TH',
            '1 timothy': '1TI', '2 timothy': '2TI',
            'hebrews': 'HEB', 'james': 'JAS',
            '1 peter': '1PE', '2 peter': '2PE',
            '1 john': '1JN', '2 john': '2JN', '3 john': '3JN',
            'jude': 'JUD', 'revelation': 'REV',
            'isaiah': 'ISA', 'jeremiah': 'JER',
            'proverbs': 'PRO', 'prov': 'PRO',
        }
        
        book_lower = book_name.lower()
        book_code = book_codes.get(book_lower)
        
        if not book_code:
            logger.warning(f"Unknown book name: {book_name}")
            return None
        
        # Build direct URL
        direct_url = f"https://www.bible.com/bible/{bible_id}/{book_code}.{chapter}.{verse}.{translation}"
        return direct_url
        
    except Exception as e:
        logger.error(f"Error converting search URL: {e}")
        return None

# Test endpoint for Bible.com URL fetching
@api_router.get("/test-fetch")
async def test_fetch_url(url: str):
    """Test endpoint to verify Bible.com URL fetching"""
    text = await fetch_verse_from_bible_com(url)
    return {"url": url, "text": text, "success": text is not None}

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
    """Add a new verse - text must be provided in exact translation"""
    # Get the next order number
    last_verse = await db.verses.find_one(sort=[("order", -1)])
    next_order = (last_verse['order'] + 1) if last_verse else 1
    
    if not verse.text or not verse.text.strip():
        raise HTTPException(status_code=400, detail="Verse text is required. Please provide the exact text in your preferred translation.")
    
    verse_doc = {
        "reference": verse.reference,
        "text": verse.text.strip(),
        "translation": verse.translation,
        "language": verse.language,
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
        "translation": verse.get('translation'),
        "language": verse.get('language'),
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
    """
    Import verses from an Excel file.
    Required columns:
    - Column A: Verse reference (e.g., "Matt 21:22" or "Jes 53:5")
    - Column B: Translation code (e.g., "NLV", "AFR53", "NIV")
    - Column C: Language (e.g., "Afr", "Eng")
    - Column D: (optional) Bible.com URL - if not provided or is a formula, URL will be built automatically
    """
    import openpyxl
    import asyncio
    import urllib.parse
    
    if not file.filename.endswith(('.xlsx', '.xls')):
        raise HTTPException(status_code=400, detail="Please upload an Excel file (.xlsx or .xls)")
    
    try:
        contents = await file.read()
        workbook = openpyxl.load_workbook(io.BytesIO(contents), data_only=True)
        sheet = workbook.active
        
        # Log the first few rows to debug
        logger.info(f"Excel file loaded. Sheet name: {sheet.title}")
        row_count = 0
        for row in sheet.iter_rows(min_row=1, max_row=5, max_col=6, values_only=True):
            logger.info(f"Row {row_count}: {row}")
            row_count += 1
        
        # Get the next order number
        last_verse = await db.verses.find_one(sort=[("order", -1)])
        next_order = (last_verse['order'] + 1) if last_verse else 1
        
        imported_count = 0
        failed_refs = []
        skipped_refs = []
        
        for row in sheet.iter_rows(min_row=1, max_col=6, values_only=True):
            reference = row[0] if len(row) > 0 else None
            translation = row[1] if len(row) > 1 else None
            language = row[2] if len(row) > 2 else None
            verse_url = row[3] if len(row) > 3 else None
            
            # Also check columns 4 and 5 in case URL is there
            if not verse_url or not str(verse_url).strip().startswith('http'):
                verse_url = row[4] if len(row) > 4 else None
            if not verse_url or not str(verse_url).strip().startswith('http'):
                verse_url = row[5] if len(row) > 5 else None
            
            if not reference or str(reference).strip() == '':
                continue
            
            # Skip header row
            if str(reference).lower() in ['reference', 'verse', 'bible verse', 'book']:
                continue
            
            reference = str(reference).strip()
            translation_str = str(translation).strip() if translation else None
            logger.info(f"Processing: {reference}, translation: {translation_str}, url: {verse_url}")
            
            # Check if verse already exists (same reference + translation)
            existing = await db.verses.find_one({
                "reference": reference,
                "translation": translation_str
            })
            if existing:
                skipped_refs.append(reference)
                continue
            
            # Build URL from reference and translation if URL is not provided or is a formula
            if not verse_url or not str(verse_url).strip().startswith('http'):
                if translation_str:
                    # Build search URL: https://www.bible.com/search/bible?query=Matt%2021:22%20NLV
                    encoded_query = urllib.parse.quote(f"{reference} {translation_str}")
                    verse_url = f"https://www.bible.com/search/bible?query={encoded_query}"
                    logger.info(f"Built URL from reference+translation: {verse_url}")
            
            # Fetch verse text from Bible.com URL
            text = None
            if verse_url and str(verse_url).strip().startswith('http'):
                url = str(verse_url).strip()
                logger.info(f"Fetching verse from URL: {url}")
                
                # Try fetching with retries
                for attempt in range(3):
                    text = await fetch_verse_from_bible_com(url)
                    if text:
                        break
                    await asyncio.sleep(1 * (attempt + 1))
            
            if not text:
                failed_refs.append(f"{reference} (could not fetch from URL)")
                continue
            
            verse_doc = {
                "reference": reference,
                "text": text,
                "translation": str(translation).strip() if translation else None,
                "language": str(language).strip() if language else None,
                "audio_base64": None,
                "order": next_order,
                "date_added": datetime.utcnow()
            }
            
            await db.verses.insert_one(verse_doc)
            next_order += 1
            imported_count += 1
            logger.info(f"Imported: {reference} ({translation})")
            
            # Rate limiting
            await asyncio.sleep(0.5)
        
        return {
            "message": f"Successfully imported {imported_count} verses",
            "imported_count": imported_count,
            "skipped_count": len(skipped_refs),
            "failed_references": failed_refs,
            "skipped_references": skipped_refs
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
