import os
import re
import asyncio
import json
import logging
import subprocess
import aiohttp
import uuid
from datetime import datetime, timedelta
from telethon import TelegramClient, events
from telethon.sessions import StringSession

# ---------------- LOGGING ----------------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger("TACTICAL_ARCHITECT")

# ---------------- CONFIG ----------------
API_ID = int(os.getenv("API_ID", 0))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
SESSION_STRING = os.getenv("SESSION_STRING", "")
CHANNELS = [c.strip() for c in os.getenv("CHANNELS", "monitorkh1654").split(",")]
GITHUB_REMOTE = os.getenv("GITHUB_REMOTE", "origin")
GITHUB_BRANCH = os.getenv("GITHUB_BRANCH", "main")

# ---------------- THREATS ----------------
THREAT_CONFIG = {
    "ballistic": {"keywords": ["баліст", "іскандер", "кинджал", "кн-23", "с-300"], "ttl": 10},
    "missile": {"keywords": ["ракета", "пуск", "х-59", "х-31", "калібр"], "ttl": 15},
    "kab": {"keywords": ["каб", "авіабомб", "керована", "уаб"], "ttl": 20},
    "shahed": {"keywords": ["шахед", "шахєд", "герань", "мопед", "бпла"], "ttl": 40},
    "recon": {"keywords": ["орлан", "зала", "розвід"], "ttl": 30},
    "unknown": {"keywords": [], "ttl": 15}
}

STATUS_MAP = {
    "detected": ["зафіксовано", "помічено", "виліт"],
    "moving": ["курс", "рухається", "через", "на"],
    "changed_direction": ["змінив", "розвернувся"],
    "lost": ["зник", "не фіксується"],
    "destroyed": ["мінус", "збито"]
}

ACTION_MAP = {
    "detected": "detected",
    "moving": "move",
    "changed_direction": "changed_direction",
    "lost": "lost",
    "destroyed": "destroyed"
}

# ---------------- STATE ----------------
class TacticalState:
    def __init__(self):
        self.targets = []
        self.reply_map = {}
        self.lock = asyncio.Lock()
        self.file = "targets.json"
        self.load()

    def load(self):
        if not os.path.exists(self.file):
            return
        try:
            with open(self.file, "r", encoding="utf-8") as f:
                self.targets = json.load(f)
                for t in self.targets:
                    if "root_message_id" in t:
                        self.reply_map[t["root_message_id"]] = t["target_id"]
        except Exception as e:
            logger.error(f"Load error: {e}")
            self.targets = []

    async def sync(self):
        async with self.lock:
            temp = f"{self.file}.tmp"
            with open(temp, "w", encoding="utf-8") as f:
                json.dump(self.targets, f, ensure_ascii=False, indent=2)
            os.replace(temp, self.file)

        proc = await asyncio.create_subprocess_exec(
            "git", "status", "--porcelain",
            stdout=subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        if not stdout.strip():
            return

        await asyncio.create_subprocess_exec("git", "add", self.file)
        await asyncio.create_subprocess_exec(
            "git", "commit", "-m", f"Tactical update {datetime.now():%H:%M:%S}"
        )
        await asyncio.create_subprocess_exec(
            "git", "push", GITHUB_REMOTE, GITHUB_BRANCH, "--force"
        )
        logger.info("GitHub synced")

state = TacticalState()

# ---------------- UTILITIES ----------------
def resolve_target_id(reply_map, reply_to_id):
    seen = set()
    cur = reply_to_id
    while cur and cur not in seen:
        seen.add(cur)
        target = reply_map.get(cur)
        if target:
            return target
        cur = None
    return None

def extract_location(text):
    text = re.sub(r"[🚨⚠️!.]", " ", text)
    m = re.search(r"(?:на|у|в|через|біля)\s+([А-ЯІЇЄ][а-яіїє']+)", text)
    if m:
        return m.group(1)
    return None

def detect_threat(text):
    tl = text.lower()
    for t, cfg in THREAT_CONFIG.items():
        if any(k in tl for k in cfg["keywords"]):
            return t
    return "unknown"

def detect_status(text):
    tl = text.lower()
    for s, keys in STATUS_MAP.items():
        if any(k in tl for k in keys):
            return s
    return "detected"

# ---------------- GEO ----------------
aiohttp_session = None

async def geocode(name):
    if not name:
        return None
    url = "https://nominatim.openstreetmap.org/search"
    params = {"q": f"{name}, Харківська область, Україна", "format": "json", "limit": 1}
    try:
        async with aiohttp_session.get(url, params=params, timeout=5) as r:
            if r.status == 200:
                d = await r.json()
                if d:
                    return float(d[0]["lat"]), float(d[0]["lon"]), d[0]["display_name"].split(",")[0]
    except:
        pass
    return None

# ---------------- TELEGRAM ----------------
client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)

@client.on(events.NewMessage(chats=CHANNELS))
async def handler(event):
    if not event.raw_text:
        return

    text = event.raw_text
    msg_id = event.id
    reply_id = event.reply_to.reply_to_msg_id if event.reply_to else None

    if any(x in text.lower() for x in ["відбій", "чисто"]):
        async with state.lock:
            state.targets = []
            state.reply_map = {}
        await state.sync()
        return

    target_id = resolve_target_id(state.reply_map, reply_id)
    location = extract_location(text)
    coords = await geocode(location) if location else None
    status = detect_status(text)

    async with state.lock:
        target = next((t for t in state.targets if t["target_id"] == target_id), None)

        if reply_id and not target:
            logger.warning("Reply without known target — ignored")
            return

        if target:
            if coords:
                target["lat"], target["lng"] = coords[:2]
                target["current_location"] = coords[2]
                if status == "detected":
                    status = "moving"

            target["status"] = status
            target["history"].append({
                "time": datetime.now().strftime("%H:%M"),
                "action": ACTION_MAP[status],
                "location": target.get("current_location")
            })

            ttl = THREAT_CONFIG[target["type"]]["ttl"]
            target["expire_at"] = (datetime.now() + timedelta(minutes=ttl)).isoformat()

            if status in ("lost", "destroyed"):
                target["expire_at"] = (datetime.now() + timedelta(seconds=30)).isoformat()

        elif coords:
            tid = str(uuid.uuid4())[:8]
            ttype = detect_threat(text)
            new = {
                "target_id": tid,
                "root_message_id": msg_id,
                "type": ttype,
                "status": status,
                "current_location": coords[2],
                "lat": coords[0],
                "lng": coords[1],
                "expire_at": (datetime.now() + timedelta(
                    minutes=THREAT_CONFIG[ttype]["ttl"])).isoformat(),
                "history": [{
                    "time": datetime.now().strftime("%H:%M"),
                    "action": "detected",
                    "location": coords[2]
                }]
            }
            state.targets.append(new)
            target_id = tid

        if target_id:
            state.reply_map[msg_id] = target_id

    await state.sync()

# ---------------- JANITOR ----------------
async def janitor():
    while True:
        await asyncio.sleep(30)
        now = datetime.now()
        async with state.lock:
            state.targets = [
                t for t in state.targets
                if datetime.fromisoformat(t["expire_at"]) > now
            ]
            active = {t["target_id"] for t in state.targets}
            state.reply_map = {
                k: v for k, v in state.reply_map.items()
                if v in active
            }
        await state.sync()

# ---------------- ENTRY ----------------
async def main():
    global aiohttp_session

    subprocess.run(["git", "config", "--global", "user.name", "TacticalBot"], check=False)
    subprocess.run(["git", "config", "--global", "user.email", "bot@tactical.local"], check=False)

    aiohttp_session = aiohttp.ClientSession(
        headers={"User-Agent": "TacticalMonitor"}
    )

    await client.start(bot_token=BOT_TOKEN)
    asyncio.create_task(janitor())
    logger.info("TACTICAL SYSTEM ONLINE")
    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())

