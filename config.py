import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN is missing in .env")

if not OWNER_ID:
    raise ValueError("OWNER_ID is missing in .env")

# Force Join Channels
FORCE_JOIN_CHANNELS = [
    "-1003998560024",
    "-1004077604887",
]
