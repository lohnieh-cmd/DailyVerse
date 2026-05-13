from fastapi import FastAPI, APIRouter, HTTPException, UploadFile, File
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
import os
import logging
from pathlib import Path
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime, date, timedelta
import httpx
import io
import re
from bs4 import BeautifulSoup

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

SUPABASE_URL = os.environ['SUPABASE_URL']
SUPABASE_KEY = os.environ['SUPABASE_KEY']

SUPABASE_HEADERS = {
    'apikey': SUPABASE_KEY,
    'Authorization': f'Bearer {SUPABASE_KEY}',
    'Content-Type': 'application/json',
}

app = FastAPI(title="Daily Scripture Verse API")
api_router = APIRouter(prefix="/api")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def to_response(doc: dict) -> dict:
    """Rename id -> _id for frontend compatibility."""
    if doc and 'id' in doc:
        doc['_id'] = doc.pop('id')
    return doc


# ==================== MODELS ====================

class VerseCreate(BaseModel):
    reference: str
    text: str
    translation: Optional[str] = None
    language: Optional[str] = None
    audio_base64: Optional[str] = None

class VerseUpdate(BaseModel):
    reference: Optional[str] = None
    text: Optional[str] = None
    translation: Optional[str] = None
    language: Optional[str] = None
    audio_base64: Optional[str] = None

class SettingsUpdate(BaseModel):
    notification_time: Optional[str] = None
    notification_enabled: Optional[bool] = None


# ==================== BIBLE API ====================

AFRIKAANS_BOOKS = {
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
    ref = reference.strip()
    match = re.match(r'^(\d?\s?[a-zA-Z]+)(\d+:\d+(?:-\d+)?)$', ref)
    if match:
        book_part = match.group(1).strip().lower()
        verse_part = match.group(2)
        for afr, eng in sorted(AFRIKAANS_BOOKS.items(), key=lambda x: -len(x[0])):
            if book_part == afr:
                return f"{eng} {verse_part}"
        return f"{book_part} {verse_part}"
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
    english_ref = convert_reference_to_english(reference)
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
            logger.warning(f"Bible API returned {response.status_code} for {reference}")
            return None
        except Exception as e:
            logger.error(f"Error fetching verse {reference}: {e}")
            return None

async def fetch_verse_from_bible_com(url: str) -> str:
    if not url or not url.strip():
        return None
    url = url.strip()
    if 'bible.com' not in url:
        return None

    start_verse = None
    end_verse = None
    if '/search/' in url:
        direct_url, start_verse, end_verse = convert_search_url_to_direct(url)
        if direct_url:
            url = direct_url

    async with httpx.AsyncClient() as client:
        try:
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
            response = await client.get(url, headers=headers, timeout=15.0, follow_redirects=True)
            if response.status_code != 200:
                return None
            html = response.text
            soup = BeautifulSoup(html, 'html.parser')

            verse_spans = soup.find_all('span', {'data-usfm': True})
            if verse_spans and start_verse is not None:
                collected_text = []
                for span in verse_spans:
                    usfm = span.get('data-usfm', '')
                    parts = usfm.split('.')
                    if len(parts) >= 3:
                        try:
                            verse_num = int(parts[-1])
                            if start_verse <= verse_num <= end_verse:
                                content = span.find('span', class_='content')
                                text = content.get_text(strip=True) if content else re.sub(r'^\d+\s*', '', span.get_text(strip=True))
                                if text:
                                    collected_text.append(text)
                        except ValueError:
                            continue
                if collected_text:
                    return ' '.join(collected_text)

            if verse_spans:
                full_text = []
                for span in verse_spans:
                    content = span.find('span', class_='content')
                    if content:
                        full_text.append(content.get_text(strip=True))
                    else:
                        text = re.sub(r'^\d+\s*', '', span.get_text(strip=True))
                        if text:
                            full_text.append(text)
                if full_text:
                    return ' '.join(full_text)

            og_desc = soup.find('meta', {'property': 'og:description'})
            if og_desc and og_desc.get('content'):
                verse_text = og_desc['content'].strip()
                if verse_text and len(verse_text) > 10 and not verse_text.startswith('Search results'):
                    return verse_text

            meta_desc = soup.find('meta', {'name': 'description'})
            if meta_desc and meta_desc.get('content'):
                verse_text = meta_desc['content'].strip()
                if verse_text and len(verse_text) > 10 and not verse_text.startswith('Search results'):
                    return verse_text

            return None
        except Exception as e:
            logger.error(f"Error fetching verse from Bible.com {url}: {e}")
            return None

def convert_search_url_to_direct(search_url: str) -> tuple:
    import urllib.parse
    try:
        parsed = urllib.parse.urlparse(search_url)
        query_params = urllib.parse.parse_qs(parsed.query)
        if 'query' not in query_params:
            return None, None, None
        query = urllib.parse.unquote(query_params['query'][0]).strip()
        parts = query.split()
        if len(parts) < 2:
            return None, None, None
        translation = parts[-1].upper()
        verse_ref = ' '.join(parts[:-1])
        bible_ids = {
            'NLV': 117, 'AFR53': 5, 'AFR83': 6, 'NIV': 111, 'KJV': 1,
            'ESV': 59, 'NLT': 116, 'NKJV': 114, 'MSG': 97, 'AMP': 8,
            'DB': 50, 'GNB': 296, 'CEV': 37, 'GNT': 68, 'FBV': 1932, 'EASY': 2079,
        }
        bible_id = bible_ids.get(translation)
        if not bible_id:
            return None, None, None
        match = re.match(r'^(\d?\s?[A-Za-z]+)\s*(\d+):(\d+(?:-\d+)?)$', verse_ref)
        if not match:
            return None, None, None
        book_name = match.group(1).strip()
        chapter = match.group(2)
        verse = match.group(3)
        start_verse = end_verse = None
        if '-' in verse:
            parts = verse.split('-')
            start_verse, end_verse = int(parts[0]), int(parts[1])
        else:
            start_verse = end_verse = int(verse)
        book_codes = {
            'matt': 'MAT', 'matteus': 'MAT', 'mark': 'MRK', 'markus': 'MRK',
            'luk': 'LUK', 'lukas': 'LUK', 'joh': 'JHN', 'johannes': 'JHN',
            'hand': 'ACT', 'rom': 'ROM', '1 kor': '1CO', '1kor': '1CO',
            '2 kor': '2CO', '2kor': '2CO', 'gal': 'GAL', 'efe': 'EPH',
            'fil': 'PHP', 'filippense': 'PHP', 'kol': 'COL',
            '1 tes': '1TH', '1tes': '1TH', '2 tes': '2TH', '2tes': '2TH',
            '1 tim': '1TI', '1tim': '1TI', '2 tim': '2TI', '2tim': '2TI',
            'tit': 'TIT', 'filem': 'PHM', 'heb': 'HEB', 'jak': 'JAS',
            '1 pet': '1PE', '1pet': '1PE', '2 pet': '2PE', '2pet': '2PE',
            '1 joh': '1JN', '1joh': '1JN', '2 joh': '2JN', '2joh': '2JN',
            '3 joh': '3JN', '3joh': '3JN', 'jud': 'JUD', 'op': 'REV',
            'gen': 'GEN', 'eks': 'EXO', 'exodus': 'EXO', 'lev': 'LEV',
            'num': 'NUM', 'deut': 'DEU', 'jos': 'JOS', 'rig': 'JDG',
            'rut': 'RUT', 'ruth': 'RUT', '1 sam': '1SA', '1sam': '1SA',
            '2 sam': '2SA', '2sam': '2SA', '1 kon': '1KI', '1kon': '1KI',
            '2 kon': '2KI', '2kon': '2KI', '1 kron': '1CH', '1kron': '1CH',
            '1 chro': '1CH', '2 kron': '2CH', '2kron': '2CH', '2 chro': '2CH',
            'esra': 'EZR', 'ezra': 'EZR', 'neh': 'NEH', 'est': 'EST',
            'job': 'JOB', 'ps': 'PSA', 'psalm': 'PSA', 'psalms': 'PSA',
            'spr': 'PRO', 'prov': 'PRO', 'pred': 'ECC', 'hgl': 'SNG',
            'jes': 'ISA', 'jer': 'JER', 'klaagl': 'LAM', 'eseg': 'EZK',
            'dan': 'DAN', 'hos': 'HOS', 'joel': 'JOL', 'amos': 'AMO',
            'ob': 'OBA', 'jona': 'JON', 'mig': 'MIC', 'nah': 'NAM',
            'hab': 'HAB', 'sef': 'ZEP', 'hag': 'HAG', 'sag': 'ZEC', 'mal': 'MAL',
            'matthew': 'MAT', 'luke': 'LUK', 'john': 'JHN', 'acts': 'ACT',
            'romans': 'ROM', '1 cor': '1CO', '2 cor': '2CO',
            '1 corinthians': '1CO', '2 corinthians': '2CO',
            'galatians': 'GAL', 'ephesians': 'EPH', 'phil': 'PHP',
            'philippians': 'PHP', 'col': 'COL', 'colossians': 'COL',
            '1 thess': '1TH', '2 thess': '2TH', '1 timothy': '1TI',
            '2 timothy': '2TI', 'hebrews': 'HEB', 'james': 'JAS',
            '1 peter': '1PE', '2 peter': '2PE', '1 john': '1JN',
            '2 john': '2JN', '3 john': '3JN', 'jude': 'JUD', 'revelation': 'REV',
            'isaiah': 'ISA', 'jeremiah': 'JER', 'ezekiel': 'EZK', 'daniel': 'DAN',
            'genesis': 'GEN', 'leviticus': 'LEV', 'numbers': 'NUM',
            'nehemiah': 'NEH', 'esther': 'EST', 'proverbs': 'PRO',
            'ecclesiastes': 'ECC', 'hosea': 'HOS', 'jonah': 'JON',
            'micah': 'MIC', 'nahum': 'NAM', 'habakkuk': 'HAB',
            'zephaniah': 'ZEP', 'haggai': 'HAG', 'zechariah': 'ZEC',
            'malachi': 'MAL', 'obadiah': 'OBA',
        }
        book_code = book_codes.get(book_name.lower())
        if not book_code:
            return None, None, None
        if start_verse != end_verse:
            direct_url = f"https://www.bible.com/bible/{bible_id}/{book_code}.{chapter}.{translation}"
        else:
            direct_url = f"https://www.bible.com/bible/{bible_id}/{book_code}.{chapter}.{verse}.{translation}"
        return direct_url, start_verse, end_verse
    except Exception as e:
        logger.error(f"Error converting search URL: {e}")
        return None, None, None


@api_router.get("/test-fetch")
async def test_fetch_url(url: str):
    text = await fetch_verse_from_bible_com(url)
    return {"url": url, "text": text, "success": text is not None}


# ==================== HOLIDAY HELPERS ====================

async def fetch_sa_holidays(year: int) -> List[dict]:
    url = f"https://date.nager.at/api/v3/PublicHolidays/{year}/ZA"
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, timeout=10.0)
            if response.status_code == 200:
                return [{'date': h['date'], 'name': h['localName']} for h in response.json()]
            return []
        except Exception as e:
            logger.error(f"Error fetching holidays: {e}")
            return []

def is_weekend(check_date: date) -> bool:
    return check_date.weekday() >= 5

async def is_holiday(check_date: date, holidays: List[dict]) -> tuple:
    date_str = check_date.isoformat()
    for h in holidays:
        if h['date'] == date_str:
            return True, h['name']
    return False, None

async def count_working_days_until(target_date: date, holidays: List[dict]) -> int:
    from datetime import timedelta
    year_start = date(target_date.year, 1, 1)
    working_days = 0
    current = year_start
    while current <= target_date:
        if not is_weekend(current):
            is_hol, _ = await is_holiday(current, holidays)
            if not is_hol:
                working_days += 1
        current = current + timedelta(days=1)
    return working_days


# ==================== SUPABASE HELPERS ====================

async def sb_get(path: str, params: dict = None) -> list:
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{SUPABASE_URL}/rest/v1/{path}",
            headers=SUPABASE_HEADERS,
            params=params or {},
        )
        resp.raise_for_status()
        return resp.json()

async def sb_post(path: str, data: dict, prefer: str = 'return=representation') -> list:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{SUPABASE_URL}/rest/v1/{path}",
            headers={**SUPABASE_HEADERS, 'Prefer': prefer},
            json=data,
        )
        resp.raise_for_status()
        return resp.json()

async def sb_patch(path: str, params: dict, data: dict) -> list:
    async with httpx.AsyncClient() as client:
        resp = await client.patch(
            f"{SUPABASE_URL}/rest/v1/{path}",
            headers={**SUPABASE_HEADERS, 'Prefer': 'return=representation'},
            params=params,
            json=data,
        )
        resp.raise_for_status()
        return resp.json()

async def sb_delete(path: str, params: dict) -> None:
    async with httpx.AsyncClient() as client:
        resp = await client.delete(
            f"{SUPABASE_URL}/rest/v1/{path}",
            headers=SUPABASE_HEADERS,
            params=params,
        )
        resp.raise_for_status()

async def sb_rpc(func: str, args: dict = None) -> any:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{SUPABASE_URL}/rest/v1/rpc/{func}",
            headers=SUPABASE_HEADERS,
            json=args or {},
        )
        resp.raise_for_status()
        return resp.json()


# ==================== VERSES ENDPOINTS ====================

@api_router.get("/")
async def root():
    return {"message": "Daily Scripture Verse API", "version": "1.0"}

@api_router.get("/verses", response_model=List[dict])
async def get_verses():
    rows = await sb_get('verses', {'order': 'order.asc', 'select': '*'})
    return [to_response(v) for v in rows]

@api_router.post("/verses")
async def create_verse(verse: VerseCreate):
    if not verse.text or not verse.text.strip():
        raise HTTPException(status_code=400, detail="Verse text is required.")

    rows = await sb_get('verses', {'select': 'order', 'order': 'order.desc', 'limit': '1'})
    next_order = (rows[0]['order'] + 1) if rows else 1

    verse_doc = {
        "reference": verse.reference,
        "text": verse.text.strip(),
        "translation": verse.translation,
        "language": verse.language,
        "audio_base64": verse.audio_base64,
        "order": next_order,
        "date_added": datetime.utcnow().isoformat(),
    }
    created = await sb_post('verses', verse_doc)
    return to_response(created[0])

@api_router.put("/verses/{verse_id}")
async def update_verse(verse_id: str, verse: VerseUpdate):
    update_data = {k: v for k, v in verse.dict().items() if v is not None}
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")

    rows = await sb_patch('verses', {'id': f'eq.{verse_id}'}, update_data)
    if not rows:
        raise HTTPException(status_code=404, detail="Verse not found")
    return to_response(rows[0])

@api_router.delete("/verses/{verse_id}")
async def delete_verse(verse_id: str):
    rows = await sb_get('verses', {'id': f'eq.{verse_id}', 'select': 'order'})
    if not rows:
        raise HTTPException(status_code=404, detail="Verse not found")
    deleted_order = rows[0]['order']

    await sb_delete('verses', {'id': f'eq.{verse_id}'})
    await sb_rpc('decrement_verse_order', {'min_order': deleted_order})

    return {"message": "Verse deleted successfully"}

@api_router.post("/verses/reorder")
async def reorder_verses(verse_ids: List[str]):
    for idx, vid in enumerate(verse_ids, start=1):
        try:
            await sb_patch('verses', {'id': f'eq.{vid}'}, {'order': idx})
        except Exception as e:
            logger.error(f"Error reordering verse {vid}: {e}")
    return {"message": "Verses reordered successfully"}


# ==================== TODAY'S VERSE ====================

@api_router.get("/verse/today")
async def get_today_verse():
    today = date.today()
    holidays = await fetch_sa_holidays(today.year)

    if is_weekend(today):
        return {"message": "No verse today - it's the weekend!", "is_weekend": True, "is_holiday": False, "date": today.isoformat()}

    is_hol, holiday_name = await is_holiday(today, holidays)
    if is_hol:
        return {"message": f"No verse today - it's {holiday_name}!", "is_weekend": False, "is_holiday": True, "holiday_name": holiday_name, "date": today.isoformat()}

    working_day_num = await count_working_days_until(today, holidays)

    all_verses = await sb_get('verses', {'select': 'id', 'order': 'order.asc'})
    total_verses = len(all_verses)

    if total_verses == 0:
        return {"message": "No verses in database. Please add some verses first.", "is_weekend": False, "is_holiday": False, "date": today.isoformat()}

    verse_index = ((working_day_num - 1) % total_verses) + 1

    rows = await sb_get('verses', {'select': '*', 'order': 'order.asc', 'limit': '1', 'offset': str(verse_index - 1)})
    verse = rows[0] if rows else None
    if not verse:
        rows = await sb_get('verses', {'select': '*', 'order': 'order.asc', 'limit': '1'})
        verse = rows[0] if rows else None

    if not verse:
        raise HTTPException(status_code=404, detail="No verse found")

    return {
        "id": verse['id'],
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
        "is_holiday": False,
    }


# ==================== HOLIDAYS ====================

@api_router.get("/holidays/{year}")
async def get_holidays(year: int):
    holidays = await fetch_sa_holidays(year)
    return {"year": year, "country": "South Africa", "holidays": holidays}


# ==================== SETTINGS ====================

@api_router.get("/settings")
async def get_settings():
    rows = await sb_get('settings', {'type': 'eq.user_settings', 'select': '*'})
    if rows:
        return to_response(rows[0])
    created = await sb_post(
        'settings',
        {"type": "user_settings", "notification_time": "07:00", "notification_enabled": True},
        prefer='return=representation',
    )
    return to_response(created[0])

@api_router.put("/settings")
async def update_settings(settings: SettingsUpdate):
    update_data = {k: v for k, v in settings.dict().items() if v is not None}
    rows = await sb_get('settings', {'type': 'eq.user_settings', 'select': 'id'})
    if rows:
        updated = await sb_patch('settings', {'type': 'eq.user_settings'}, update_data)
        return to_response(updated[0])
    else:
        created = await sb_post('settings', {"type": "user_settings", **update_data})
        return to_response(created[0])


# ==================== EXCEL IMPORT ====================

@api_router.post("/import/excel")
async def import_excel(file: UploadFile = File(...)):
    import openpyxl
    import asyncio
    import urllib.parse

    if not file.filename.endswith(('.xlsx', '.xls')):
        raise HTTPException(status_code=400, detail="Please upload an Excel file (.xlsx or .xls)")

    try:
        contents = await file.read()
        workbook = openpyxl.load_workbook(io.BytesIO(contents), data_only=True)
        sheet = workbook.active

        rows_existing = await sb_get('verses', {'select': 'order', 'order': 'order.desc', 'limit': '1'})
        next_order = (rows_existing[0]['order'] + 1) if rows_existing else 1

        imported_count = 0
        failed_refs = []
        skipped_refs = []

        for row in sheet.iter_rows(min_row=1, max_col=6, values_only=True):
            reference = row[0] if len(row) > 0 else None
            translation = row[1] if len(row) > 1 else None
            language = row[2] if len(row) > 2 else None
            verse_url = row[3] if len(row) > 3 else None

            if not verse_url or not str(verse_url).strip().startswith('http'):
                verse_url = row[4] if len(row) > 4 else None
            if not verse_url or not str(verse_url).strip().startswith('http'):
                verse_url = row[5] if len(row) > 5 else None

            if not reference or str(reference).strip() == '':
                continue
            if str(reference).lower() in ['reference', 'verse', 'bible verse', 'book']:
                continue

            reference = str(reference).strip()
            translation_str = str(translation).strip() if translation else None

            existing = await sb_get('verses', {
                'reference': f'eq.{reference}',
                'translation': f'eq.{translation_str}',
                'select': 'id',
                'limit': '1',
            })
            if existing:
                skipped_refs.append(reference)
                continue

            if not verse_url or not str(verse_url).strip().startswith('http'):
                if translation_str:
                    encoded_query = urllib.parse.quote(f"{reference} {translation_str}")
                    verse_url = f"https://www.bible.com/search/bible?query={encoded_query}"

            text = None
            if verse_url and str(verse_url).strip().startswith('http'):
                for attempt in range(3):
                    text = await fetch_verse_from_bible_com(str(verse_url).strip())
                    if text:
                        break
                    await asyncio.sleep(1 * (attempt + 1))

            if not text:
                failed_refs.append(f"{reference} (could not fetch from URL)")
                continue

            verse_doc = {
                "reference": reference,
                "text": text,
                "translation": translation_str,
                "language": str(language).strip() if language else None,
                "audio_base64": None,
                "order": next_order,
                "date_added": datetime.utcnow().isoformat(),
            }
            await sb_post('verses', verse_doc, prefer='return=minimal')
            next_order += 1
            imported_count += 1
            await asyncio.sleep(0.5)

        return {
            "message": f"Successfully imported {imported_count} verses",
            "imported_count": imported_count,
            "skipped_count": len(skipped_refs),
            "failed_references": failed_refs,
            "skipped_references": skipped_refs,
        }

    except Exception as e:
        logger.error(f"Error importing Excel: {e}")
        raise HTTPException(status_code=500, detail=f"Error processing Excel file: {str(e)}")


# ==================== SEED DATA ====================

@api_router.post("/seed")
async def seed_sample_verses():
    sample_verses = [
        "Numbers 6:24-26", "Job 33:4", "2 Peter 1:20-21", "Psalm 23:1-3",
        "John 3:16", "Romans 8:28", "Philippians 4:13", "Jeremiah 29:11",
        "Proverbs 3:5-6", "Isaiah 41:10",
    ]
    existing_count = len(await sb_get('verses', {'select': 'id'}))
    if existing_count > 0:
        return {"message": f"Database already has {existing_count} verses. Clear first if you want to reseed."}

    imported_count = 0
    failed_refs = []
    for idx, reference in enumerate(sample_verses, start=1):
        text = await fetch_verse_from_api(reference)
        if not text:
            failed_refs.append(reference)
            continue
        await sb_post('verses', {
            "reference": reference,
            "text": text,
            "audio_base64": None,
            "order": idx,
            "date_added": datetime.utcnow().isoformat(),
        }, prefer='return=minimal')
        imported_count += 1

    return {"message": f"Seeded {imported_count} sample verses", "imported_count": imported_count, "failed_references": failed_refs}

@api_router.delete("/verses")
async def clear_all_verses():
    count = await sb_rpc('clear_all_verses')
    return {"message": f"Deleted {count} verses"}

class BulkVerseImport(BaseModel):
    references: List[str]

@api_router.post("/import/bulk")
async def import_bulk_verses(data: BulkVerseImport):
    import asyncio

    rows_existing = await sb_get('verses', {'select': 'order', 'order': 'order.desc', 'limit': '1'})
    next_order = (rows_existing[0]['order'] + 1) if rows_existing else 1

    imported_count = 0
    failed_refs = []
    skipped_refs = []

    for reference in data.references:
        reference = reference.strip()
        if not reference:
            continue
        existing = await sb_get('verses', {'reference': f'eq.{reference}', 'select': 'id', 'limit': '1'})
        if existing:
            skipped_refs.append(reference)
            continue

        text = None
        for attempt in range(3):
            text = await fetch_verse_from_api(reference)
            if text:
                break
            await asyncio.sleep(1 * (attempt + 1))

        if not text:
            failed_refs.append(reference)
            continue

        await sb_post('verses', {
            "reference": reference,
            "text": text,
            "audio_base64": None,
            "order": next_order,
            "date_added": datetime.utcnow().isoformat(),
        }, prefer='return=minimal')
        next_order += 1
        imported_count += 1
        await asyncio.sleep(0.5)

    return {
        "message": f"Successfully imported {imported_count} verses",
        "imported_count": imported_count,
        "skipped_count": len(skipped_refs),
        "failed_references": failed_refs,
        "skipped_references": skipped_refs,
    }


# ==================== BULK AUDIO IMPORT ====================

@api_router.post("/import/audio-bulk")
async def import_audio_bulk(file: UploadFile = File(...)):
    """
    Import audio files from a ZIP archive and attach them to matching verses.
    Each audio file should be named after the verse reference, e.g. "John 3:16.m4a".
    Matching is case-insensitive and ignores spaces/punctuation differences.
    """
    import zipfile
    import base64

    if not file.filename.lower().endswith('.zip'):
        raise HTTPException(status_code=400, detail="Please upload a ZIP file containing your audio recordings.")

    contents = await file.read()

    # Load all verses for matching
    all_verses = await sb_get('verses', {'select': 'id,reference', 'order': 'order.asc'})
    if not all_verses:
        raise HTTPException(status_code=400, detail="No verses in database to match against.")

    def normalise(s: str) -> str:
        return re.sub(r'[\s\-:.,]', '', s).lower()

    verse_map = {normalise(v['reference']): v for v in all_verses}

    matched = []
    unmatched = []
    audio_extensions = {'.m4a', '.mp3', '.wav', '.aac', '.mp4', '.ogg'}

    try:
        with zipfile.ZipFile(io.BytesIO(contents)) as zf:
            for entry in zf.infolist():
                if entry.is_dir():
                    continue
                name = Path(entry.filename).name
                stem = Path(name).stem
                suffix = Path(name).suffix.lower()

                if suffix not in audio_extensions:
                    continue

                key = normalise(stem)
                verse = verse_map.get(key)
                if not verse:
                    unmatched.append(name)
                    continue

                audio_data = zf.read(entry.filename)
                audio_b64 = base64.b64encode(audio_data).decode('utf-8')

                await sb_patch('verses', {'id': f'eq.{verse["id"]}'}, {'audio_base64': audio_b64})
                matched.append(stem)
                logger.info(f"Attached audio to verse: {verse['reference']}")

    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="Invalid ZIP file.")

    return {
        "message": f"Attached audio to {len(matched)} verses.",
        "matched_count": len(matched),
        "matched": matched,
        "unmatched_count": len(unmatched),
        "unmatched": unmatched,
    }


# ==================== APP SETUP ====================

app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
