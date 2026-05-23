from urllib.parse import unquote
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests
import logging
import os
import sys
import time

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# 🌏 TIMEZONE
# ──────────────────────────────────────────────

IST = ZoneInfo("Asia/Kolkata")

# ──────────────────────────────────────────────
# ✏️  YOUR CREDENTIALS
# ──────────────────────────────────────────────

AT_COOKIE = os.getenv("AT_COOKIE")
ST_COOKIE = os.getenv("ST_COOKIE")
DEVICE_ID = os.getenv("DEVICE_ID")

API_KEY   = "9d153009-e961-4718-a343-2a36b0a1d1fd"
CENTER_ID = 100

# ──────────────────────────────────────────────
# 🎯  YOUR PREFERENCES
# ──────────────────────────────────────────────

PREFERRED_CLASSES = [
    "HRX",
    "Strength",
    "Dance",
]

PREFERRED_SLOTS = [
    "07:00",
    "08:00",
]

BOOK_DAYS_AHEAD      = 4
RETRY_COUNT          = 5
RETRY_WAIT_SECONDS   = 5
LOG_DIR              = "./logs"
BASE_URL             = "https://www.cult.fit"

# ──────────────────────────────────────────────
# 🌐 REQUEST SESSION
# ──────────────────────────────────────────────

session = requests.Session()

print("AT_COOKIE:", AT_COOKIE)
print("ST_COOKIE:", ST_COOKIE)
print("DEVICE_ID:", DEVICE_ID)

session.cookies.set("at",       unquote(AT_COOKIE))
session.cookies.set("st",       unquote(ST_COOKIE))
session.cookies.set("deviceId", DEVICE_ID)

COMMON_HEADERS = {
    "accept":       "application/json",
    "apikey":       API_KEY,
    "appversion":   "7",
    "browsername":  "Web",
    "osname":       "browser",
    "timezone":     "Asia/Kolkata",
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/147.0.0.0 Safari/537.36"
    )
}

# ──────────────────────────────────────────────
# 🔧 LOGGING
# ──────────────────────────────────────────────

def setup_logging():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

    os.makedirs(LOG_DIR, exist_ok=True)
    log_file = os.path.join(
        LOG_DIR,
        f"CultFitBooker_{datetime.now(IST).strftime('%Y-%m-%d')}.log"
    )

    logger.setLevel(logging.INFO)
    fmt = logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    fh = logging.FileHandler(log_file, encoding='utf-8')
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter('%(message)s'))
    logger.addHandler(ch)

# ──────────────────────────────────────────────
# 🔐 VERIFY LOGIN
# ──────────────────────────────────────────────

def verify_login() -> bool:
    try:
        r = session.get(
            f"{BASE_URL}/api/cult/classes/v2?productType=FITNESS&centreId={CENTER_ID}",
            headers=COMMON_HEADERS,
            timeout=20
        )
        if r.status_code == 401:
            logger.error("❌ Unauthorized — cookies expired.")
            return False
        logger.info("✅ Login verified.")
        return True
    except Exception as e:
        logger.error(f"❌ Login check failed: {e}")
        return False

# ──────────────────────────────────────────────
# 🔍 CHECK EXISTING BOOKING
# ──────────────────────────────────────────────

def is_already_booked(date_str: str) -> bool:
    """
    Returns True if there is already a confirmed booking
    for the given date at CENTER_ID.
    Checks the class list for the date — if any class has
    state containing 'BOOKED' or 'BOOKING_CONFIRMED', we skip.
    """
    try:
        r = session.get(
            f"{BASE_URL}/api/cult/classes/v2?productType=FITNESS&centreId={CENTER_ID}",
            headers=COMMON_HEADERS,
            timeout=20
        )
        if r.status_code != 200:
            logger.warning(f"⚠️ Could not check existing bookings (HTTP {r.status_code}) — proceeding anyway.")
            return False

        data       = r.json()
        date_block = data.get("classByDateMap", {}).get(date_str, {})
        time_slots = date_block.get("classByTimeList", [])

        for slot in time_slots:
            for center_block in slot.get("centerWiseClasses", []):
                if int(center_block.get("centerId", -1)) == int(CENTER_ID):
                    for c in center_block.get("classes", []):
                        state = c.get("state", "").upper()
                        if any(s in state for s in ("BOOKED", "BOOKING_CONFIRMED", "CHECKED_IN")):
                            name  = c.get("workoutName", "?")
                            stime = c.get("startTime", "?")
                            logger.info(f"✅ Already booked: {name} @ {stime} on {date_str} — skipping.")
                            return True

        return False

    except Exception as e:
        logger.warning(f"⚠️ Booking check error: {e} — proceeding anyway.")
        return False

# ──────────────────────────────────────────────
# 📅 FETCH CLASSES
# ──────────────────────────────────────────────

def fetch_classes(date_str: str):
    r = session.get(
        f"{BASE_URL}/api/cult/classes/v2?productType=FITNESS&centreId={CENTER_ID}",
        headers=COMMON_HEADERS,
        timeout=30
    )

    if r.status_code != 200:
        logger.error(f"❌ Fetch failed: HTTP {r.status_code}")
        return None

    data            = r.json()
    available_dates = list(data.get("classByDateMap", {}).keys())
    logger.info(f"📦 Available dates: {available_dates}")

    if date_str not in available_dates:
        logger.warning(f"⚠️ Target date {date_str} not released yet.")
        return None

    date_block = data.get("classByDateMap", {}).get(date_str, {})
    time_slots = date_block.get("classByTimeList", [])

    classes = []
    for slot in time_slots:
        for center_block in slot.get("centerWiseClasses", []):
            if int(center_block.get("centerId", -1)) == int(CENTER_ID):
                classes.extend(center_block.get("classes", []))

    return classes

# ──────────────────────────────────────────────
# 🧠 FIND BEST CLASS
# ──────────────────────────────────────────────

def find_best_class(classes: list) -> dict | None:
    """
    Priority:
      1. Morning slots first (all preferred classes), then evening
      2. Within each time bucket: class order from PREFERRED_CLASSES
      3. Within each class: slot order from PREFERRED_SLOTS
    Only considers AVAILABLE / BOOK_NOW states (no waitlist).
    """
    MORNING_SLOTS  = {t for t in PREFERRED_SLOTS if int(t.split(":")[0]) < 12}
    EVENING_SLOTS  = {t for t in PREFERRED_SLOTS if int(t.split(":")[0]) >= 12}
    PRIORITY_STATES = {"AVAILABLE", "BOOK_NOW"}

    for time_bucket in [MORNING_SLOTS, EVENING_SLOTS]:
        if not time_bucket:
            continue
        for pref in PREFERRED_CLASSES:
            matches = [
                c for c in classes
                if pref.lower() in c.get("workoutName", "").lower()
                and c.get("startTime", "")[:5] in time_bucket
                and c.get("state", "").upper() in PRIORITY_STATES
            ]
            matches.sort(key=lambda c: next(
                (i for i, t in enumerate(PREFERRED_SLOTS)
                 if c.get("startTime", "")[:5] == t), 99
            ))
            if matches:
                return matches[0]

    return None

# ──────────────────────────────────────────────
# 🎯 BOOK CLASS
# ──────────────────────────────────────────────

def book_class(c: dict) -> bool:
    class_id = str(c["id"])
    name     = c.get("workoutName")
    stime    = c.get("startTime")
    date     = c.get("date")

    logger.info(f"\n🎯 Booking: {name} @ {stime} on {date}")

    headers = {**COMMON_HEADERS, "content-type": "application/json"}

    r = session.post(
        f"{BASE_URL}/api/cult/class/{class_id}/book",
        headers=headers,
        json={},
        timeout=20
    )

    logger.info(f"📡 HTTP {r.status_code}")

    try:
        body = r.json()
    except Exception:
        body = r.text[:300]

    if r.status_code in (200, 201):
        logger.info("✅ BOOKED SUCCESSFULLY")
        logger.info(f"📄 Response: {body}")
        return True
    elif r.status_code == 409:
        logger.info("ℹ️ Already booked.")
        return True
    elif r.status_code == 401:
        logger.error("❌ Unauthorized — cookies expired.")
        return False
    elif r.status_code == 403:
        logger.error(f"❌ Booking not allowed yet: {body}")
        return False
    else:
        logger.error(f"❌ Booking failed: {body}")
        return False

# ──────────────────────────────────────────────
# 🚀 MAIN
# ──────────────────────────────────────────────

def run():
    setup_logging()

    logger.info("=" * 60)
    logger.info("🏋️  CULT.FIT AUTO BOOKER (API VERSION)")
    logger.info("=" * 60)

    ist_now     = datetime.now(IST)
    target_date = (ist_now + timedelta(days=BOOK_DAYS_AHEAD)).strftime("%Y-%m-%d")
    target_str  = (ist_now + timedelta(days=BOOK_DAYS_AHEAD)).strftime("%A, %d %b")

    logger.info(f"🕒 Current IST time : {ist_now.strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"📅 Booking for      : {target_str} ({target_date})")

    if not verify_login():
        return

    # ── Check if already booked for target date ───────────────
    logger.info(f"\n🔍 Checking existing bookings for {target_str}...")
    if is_already_booked(target_date):
        logger.info("🎉 Already have a booking — nothing to do!")
        return

    logger.info("  No existing booking found — proceeding.")

    # ── Fetch classes with retry ──────────────────────────────
    classes = None
    for attempt in range(1, RETRY_COUNT + 1):
        logger.info(f"\n🔍 Fetch attempt {attempt}/{RETRY_COUNT}...")
        classes = fetch_classes(target_date)

        if classes is not None:
            logger.info(f"✅ Found {len(classes)} classes.")
            break

        logger.info(f"⏳ Not released yet — retrying in {RETRY_WAIT_SECONDS}s...")
        time.sleep(RETRY_WAIT_SECONDS)

    if classes is None:
        logger.error("❌ Target date never became available after all retries.")
        return

    if not classes:
        logger.error("❌ No classes returned for target date.")
        return

    # ── Print all classes ─────────────────────────────────────
    logger.info(f"\n📋 All classes on {target_str}:\n")
    for c in sorted(classes, key=lambda x: x.get("startTime", "")):
        logger.info(
            f"  {c.get('workoutName','?'):35s}  "
            f"{c.get('startTime','?')}  "
            f"seats={c.get('availableSeats','?')}  "
            f"state={c.get('state','?')}"
        )

    # ── Find and book best class ──────────────────────────────
    best = find_best_class(classes)

    if not best:
        logger.warning("\n⚠️  No preferred available class found.")
        logger.info("Tip: Check class names above and update PREFERRED_CLASSES.")
        return

    logger.info(
        f"\n🏆 Best match: {best.get('workoutName')} "
        f"@ {best.get('startTime')} [{best.get('state')}]"
    )

    if book_class(best):
        logger.info("\n🎉 BOOKING COMPLETE!")
    else:
        logger.error("\n❌ BOOKING FAILED.")


if __name__ == "__main__":
    run()
