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

API_KEY = "9d153009-e961-4718-a343-2a36b0a1d1fd"
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

# Run after 10 PM IST release
BOOK_DAYS_AHEAD = 4

# Retry aggressively around release time
RETRY_COUNT = 30
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

    url = (
        f"{BASE_URL}/api/cult/classes/v2"
        f"?productType=FITNESS&centreId={CENTER_ID}"
    )

    r = session.get(
        url,
        headers=COMMON_HEADERS,
        timeout=30
    )

    if r.status_code != 200:
        logger.error(f"❌ Fetch failed: HTTP {r.status_code}")
        return None

    data = r.json()

    available_dates = list(
        data.get("classByDateMap", {}).keys()
    )

    logger.info(
        f"📦 Available dates: {available_dates}"
    )

    # Date not released yet
    if date_str not in available_dates:

        logger.warning(
            f"⚠️ Target date {date_str} not released yet."
        )

        return None

    date_block = (
        data.get("classByDateMap", {})
        .get(date_str, {})
    )

    time_slots = date_block.get("classByTimeList", [])

    classes = []

    for slot in time_slots:

        for center_block in slot.get(
            "centerWiseClasses",
            []
        ):

            if int(center_block.get("centerId", -1)) == int(CENTER_ID):

                classes.extend(
                    center_block.get("classes", [])
                )

    return classes

# ──────────────────────────────────────────────
# 🧠 FIND BEST CLASS
# ──────────────────────────────────────────────

def find_best_class(classes):

    PRIORITY_STATES = [
        "AVAILABLE",
        "BOOK_NOW"
    ]

    candidates = []

    for c in classes:

        name = c.get("workoutName", "").lower()
        stime = c.get("startTime", "")[:5]
        state = c.get("state", "").upper()

        # Preferred class filter
        if not any(
            pref.lower() in name
            for pref in PREFERRED_CLASSES
        ):
            continue

        # Preferred slot filter
        if stime not in PREFERRED_SLOTS:
            continue

        # Ignore waitlist completely
        if state not in PRIORITY_STATES:
            continue

        class_priority = next(
            (
                i for i, p in enumerate(PREFERRED_CLASSES)
                if p.lower() in name
            ),
            999
        )

        slot_priority = next(
            (
                i for i, t in enumerate(PREFERRED_SLOTS)
                if stime == t
            ),
            999
        )

        state_priority = PRIORITY_STATES.index(state)

        candidates.append((
            class_priority,
            slot_priority,
            state_priority,
            c
        ))

    if not candidates:
        return None

    candidates.sort()

    return candidates[0][3]

# ──────────────────────────────────────────────
# 🎯 BOOK CLASS
# ──────────────────────────────────────────────

def book_class(c):

    class_id = str(c["id"])

    name = c.get("workoutName")
    stime = c.get("startTime")
    date = c.get("date")

    logger.info(
        f"\n🎯 Booking: "
        f"{name} @ {stime} on {date}"
    )

    url = (
        f"{BASE_URL}/api/cult/class/"
        f"{class_id}/book"
    )

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

        logger.error(
            f"❌ Booking not allowed yet: {body}"
        )

        return False

    else:

        logger.error(
            f"❌ Booking failed: {body}"
        )

        return False

# ──────────────────────────────────────────────
# 🚀 MAIN
# ──────────────────────────────────────────────

def run():

    setup_logging()

    logger.info("=" * 60)
    logger.info("🏋️ CULT.FIT AUTO BOOKER (API VERSION)")
    logger.info("=" * 60)

    ist_now = datetime.now(IST)

    logger.info(
        f"🕒 Current IST time: "
        f"{ist_now.strftime('%Y-%m-%d %H:%M:%S')}"
    )

    target_date = (
        ist_now
        + timedelta(days=BOOK_DAYS_AHEAD)
    ).strftime("%Y-%m-%d")

    logger.info(
        f"📅 Booking target date: {target_date}"
    )

    if not verify_login():
        return

    classes = None

    for attempt in range(1, RETRY_COUNT + 1):

        logger.info(
            f"\n🔍 Fetch attempt "
            f"{attempt}/{RETRY_COUNT}"
        )

        classes = fetch_classes(target_date)

        # Date not released yet
        if classes is None:

            logger.info(
                f"⏳ Date not released yet. "
                f"Retrying in "
                f"{RETRY_WAIT_SECONDS}s..."
            )

            time.sleep(RETRY_WAIT_SECONDS)
            continue

        logger.info(
            f"✅ Found {len(classes)} classes."
        )

        break

    if classes is None:

        logger.error(
            "❌ Date never became available."
        )

        return

    if not classes:

        logger.error(
            "❌ No classes available."
        )

        return

    logger.info("\n📋 ALL CLASSES:\n")

    for c in sorted(
        classes,
        key=lambda x: x.get("startTime", "")
    ):

        logger.info(
            f"{c.get('workoutName'):30s} "
            f"{c.get('startTime')} "
            f"state={c.get('state')}"
        )

    best = find_best_class(classes)

    if not best:

        logger.warning(
            "⚠️ No preferred class found."
        )

        return

    logger.info(
        f"\n🏆 Best match: "
        f"{best.get('workoutName')} "
        f"@ {best.get('startTime')} "
        f"[{best.get('state')}]"
    )

    success = book_class(best)

    if success:
        logger.info("\n🎉 BOOKING FLOW COMPLETED")
    else:
        logger.error("\n❌ BOOKING FLOW FAILED")

# ──────────────────────────────────────────────

if __name__ == "__main__":
    run()