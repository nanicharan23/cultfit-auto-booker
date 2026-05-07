from urllib.parse import unquote
from datetime import datetime, timedelta
import requests
import logging
import os
import sys
import time

logger = logging.getLogger(__name__)

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
    "20:00",
]

BOOK_DAYS_AHEAD = 3

# Retry aggressively around 10PM release
RETRY_COUNT = 20
RETRY_WAIT_SECONDS = 5

LOG_DIR = "./logs"

BASE_URL = "https://www.cult.fit"

# ──────────────────────────────────────────────
# 🌐 REQUEST SESSION
# ──────────────────────────────────────────────

session = requests.Session()

session.cookies.set("at", unquote(AT_COOKIE))
session.cookies.set("st", unquote(ST_COOKIE))
session.cookies.set("deviceId", DEVICE_ID)

COMMON_HEADERS = {
    "accept": "application/json",
    "apikey": API_KEY,
    "appversion": "7",
    "browsername": "Web",
    "osname": "browser",
    "timezone": "Asia/Kolkata",
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
        f"CultFitBooker_{datetime.now().strftime('%Y-%m-%d')}.log"
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

def verify_login():
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
# 📅 FETCH CLASSES
# ──────────────────────────────────────────────

def fetch_classes(date_str: str):

    url = f"{BASE_URL}/api/cult/classes/v2?productType=FITNESS&centreId={CENTER_ID}"

    r = session.get(
        url,
        headers=COMMON_HEADERS,
        timeout=30
    )

    if r.status_code != 200:
        logger.error(f"❌ Fetch failed: HTTP {r.status_code}")
        return []

    data = r.json()

    logger.info(
        f"📦 Available dates: "
        f"{list(data.get('classByDateMap', {}).keys())}"
    )

    date_block = data.get("classByDateMap", {}).get(date_str, {})
    time_slots = date_block.get("classByTimeList", [])

    classes = []

    for slot in time_slots:
        for center_block in slot.get("centerWiseClasses", []):

            if int(center_block.get("centerId", -1)) == int(CENTER_ID):
                classes.extend(center_block.get("classes", []))

    return classes

# ──────────────────────────────────────────────
# 🎯 BOOK CLASS
# ──────────────────────────────────────────────

def book_class(c):

    class_id = str(c["id"])

    name = c.get("workoutName")
    stime = c.get("startTime")
    date = c.get("date")

    logger.info(f"\n🎯 Booking: {name} @ {stime} on {date}")

    url = f"{BASE_URL}/api/cult/class/{class_id}/book"

    headers = COMMON_HEADERS.copy()
    headers["content-type"] = "application/json"

    r = session.post(
        url,
        headers=headers,
        json={},
        timeout=20
    )

    logger.info(f"📡 HTTP {r.status_code}")

    try:
        body = r.json()
    except:
        body = r.text[:300]

    if r.status_code in (200, 201):
        logger.info("✅ BOOKED SUCCESSFULLY")
        return True

    elif r.status_code == 409:
        logger.info("ℹ️ Already booked.")
        return True

    elif r.status_code == 401:
        logger.error("❌ Unauthorized — cookies expired.")
        return False

    else:
        logger.error(f"❌ Booking failed: {body}")
        return False

# ──────────────────────────────────────────────
# 🧠 FIND BEST CLASS
# ──────────────────────────────────────────────

def find_best_class(classes):

    for pref in PREFERRED_CLASSES:

        matches = [
            c for c in classes
            if pref.lower() in c.get("workoutName", "").lower()
            and c.get("startTime", "")[:5] in PREFERRED_SLOTS
            and any(
                x in c.get("state", "").upper()
                for x in ("AVAILABLE", "BOOK_NOW")
            )
        ]

        matches.sort(
            key=lambda c: next(
                (
                    i for i, t in enumerate(PREFERRED_SLOTS)
                    if c.get("startTime", "")[:5] == t
                ),
                99
            )
        )

        if matches:
            return matches[0]

    return None

# ──────────────────────────────────────────────
# 🚀 MAIN
# ──────────────────────────────────────────────

def run():

    setup_logging()

    logger.info("=" * 60)
    logger.info("🏋️ CULT.FIT AUTO BOOKER (API VERSION)")
    logger.info("=" * 60)

    target_date = (
        datetime.now() + timedelta(days=BOOK_DAYS_AHEAD)
    ).strftime("%Y-%m-%d")

    logger.info(f"📅 Booking for: {target_date}")

    if not verify_login():
        return

    classes = []

    for attempt in range(1, RETRY_COUNT + 1):

        logger.info(
            f"\n🔍 Fetch attempt "
            f"{attempt}/{RETRY_COUNT}"
        )

        classes = fetch_classes(target_date)

        if classes:
            logger.info(f"✅ Found {len(classes)} classes.")
            break

        logger.info(
            f"⏳ No classes yet. "
            f"Retrying in {RETRY_WAIT_SECONDS}s..."
        )

        time.sleep(RETRY_WAIT_SECONDS)

    if not classes:
        logger.error("❌ No classes found.")
        return

    logger.info("\n📋 ALL CLASSES:\n")

    for c in sorted(classes, key=lambda x: x.get("startTime", "")):

        logger.info(
            f"{c.get('workoutName'):30s} "
            f"{c.get('startTime')} "
            f"state={c.get('state')}"
        )

    best = find_best_class(classes)

    if not best:
        logger.warning("⚠️ No preferred class available.")
        return

    logger.info(
        f"\n🏆 Best match: "
        f"{best.get('workoutName')} "
        f"@ {best.get('startTime')}"
    )

    book_class(best)

    logger.info("\n✅ DONE")

# ──────────────────────────────────────────────

if __name__ == "__main__":
    run()