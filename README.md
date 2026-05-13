# DailyVerse

A mobile app that delivers a daily Bible verse with audio narration. Built with React Native (Expo) on the front end, FastAPI on the back end, Supabase as the database, and deployed to Vercel.

---

## Tech Stack

| Layer      | Technology                              |
|------------|-----------------------------------------|
| Frontend   | React Native + Expo (Expo Go / EAS)     |
| Backend    | FastAPI (Python), deployed on Vercel    |
| Database   | Supabase (PostgreSQL via PostgREST)     |
| Audio      | Base64-encoded audio stored in Supabase |

---

## Project Structure

```
DailyVerse/
├── backend/
│   ├── server.py          # FastAPI app — all API routes
│   ├── requirements.txt   # Python dependencies
│   ├── vercel.json        # Vercel deployment config
│   ├── api/
│   │   └── index.py       # Vercel entry point (imports server.py)
│   └── .env               # Local secrets (never committed)
└── frontend/
    ├── app/               # Expo Router screens
    │   ├── index.tsx      # Home screen (today's verse + audio)
    │   ├── settings.tsx   # Settings & admin tools
    │   └── ...
    ├── .env               # Frontend env vars (EXPO_PUBLIC_*)
    └── package.json
```

---

## Environment Variables

### Backend (`backend/.env`)

```env
SUPABASE_URL=https://<your-project>.supabase.co
SUPABASE_KEY=<your-supabase-anon-key>
```

### Frontend (`frontend/.env`)

```env
EXPO_PUBLIC_BACKEND_URL=https://<your-vercel-deployment>.vercel.app
```

> **Note:** `EXPO_PUBLIC_*` variables are baked in at Metro bundler start time. After changing this value, restart `npx expo start`.

---

## Supabase Setup

1. Create a Supabase project at [supabase.com](https://supabase.com).
2. Run the following SQL in the Supabase SQL editor to create required tables and helper functions:

```sql
-- Verses table
CREATE TABLE verses (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  reference   TEXT NOT NULL,
  text        TEXT,
  translation TEXT,
  language    TEXT,
  audio_base64 TEXT,
  "order"     INT,
  date_added  TIMESTAMPTZ DEFAULT NOW()
);

-- Settings table
CREATE TABLE settings (
  id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  type                  TEXT UNIQUE,
  notification_time     TEXT,
  notification_enabled  BOOLEAN DEFAULT TRUE
);

-- Helper: shift order values down (used when deleting a verse)
CREATE OR REPLACE FUNCTION decrement_verse_order(min_order INT)
RETURNS void LANGUAGE sql AS $$
  UPDATE verses SET "order" = "order" - 1 WHERE "order" > min_order;
$$;

-- Helper: delete all verses (used by admin reset)
CREATE OR REPLACE FUNCTION clear_all_verses()
RETURNS void LANGUAGE sql AS $$
  DELETE FROM verses;
$$;
```

3. RLS (Row Level Security) can remain **disabled** for the anon key to have full read/write access.

---

## Local Development

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn server:app --reload --port 8000
```

The API will be available at `http://localhost:8000`.

### Frontend

```bash
cd frontend
npm install
npx expo start
```

- Scan the QR code with **Expo Go** on your phone (iOS/Android).
- Make sure `EXPO_PUBLIC_BACKEND_URL` in `frontend/.env` points to your running backend (local IP for local dev, Vercel URL for production).

For local testing on a physical device, use your machine's LAN IP:

```env
EXPO_PUBLIC_BACKEND_URL=http://10.0.0.x:8000
```

---

## Deploying the Backend to Vercel

1. Install the Vercel CLI: `npm i -g vercel`
2. From the `backend/` directory:

```bash
cd backend
vercel --prod
```

3. Set environment variables in the Vercel dashboard (or via CLI):

```bash
vercel env add SUPABASE_URL
vercel env add SUPABASE_KEY
```

4. After deployment, copy the production URL and update `frontend/.env`:

```env
EXPO_PUBLIC_BACKEND_URL=https://your-deployment.vercel.app
```

---

## API Endpoints

| Method | Path                        | Description                          |
|--------|-----------------------------|--------------------------------------|
| GET    | `/api/verse/today`          | Get the current verse (by day index) |
| GET    | `/api/verses`               | List all verses                      |
| POST   | `/api/verses`               | Add a new verse                      |
| PUT    | `/api/verses/{id}`          | Update a verse                       |
| DELETE | `/api/verses/{id}`          | Delete a verse                       |
| GET    | `/api/settings`             | Get notification settings            |
| PUT    | `/api/settings`             | Update notification settings         |
| POST   | `/api/import/audio-bulk`    | Bulk-import audio from a ZIP file    |

---

## Bulk Audio Import

Audio files can be bulk-imported via the Settings screen in the app, or directly via the `/api/import/audio-bulk` endpoint.

**ZIP file convention:**
- Filename stem = Bible reference, e.g. `Joh 3:16.m4a` or `Romans 8:28.m4a`
- Supported formats: `.m4a`, `.mp3`, `.wav`, `.aac`, `.mp4`, `.ogg`
- Afrikaans references use Afrikaans book abbreviations (Joh, Ps, Spr, Jes, etc.)

The import endpoint matches each audio file to its verse in the database by reference and updates the `audio_base64` field.

---

## Importing Verses (Initial Setup)

Use the standalone Python scripts in the parent directory for a one-time bulk import:

```bash
# First pass — imports all verses from ZIP files
python import_audio.py

# Second pass — retries any that failed (rate limiting, typos, etc.)
python import_audio_retry.py
```

These scripts read audio from local ZIP files, fetch verse text from [bible-api.com](https://bible-api.com), and insert everything directly into Supabase.

---

## Notifications

Daily verse notifications are scheduled client-side using Expo's notification API. Configure the notification time in the app's Settings screen.

---

## License

Private — all rights reserved.
