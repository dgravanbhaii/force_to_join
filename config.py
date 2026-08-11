import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN is missing in .env")

if not OWNER_ID:
    raise ValueError("OWNER_ID is missing in .env")

# ============================================================
# FORCE JOIN CHANNELS
# IMPORTANT:
# - Bot must be ADMIN in every channel listed here
# - "link" must be a real invite link (or public @username link)
#   the bot generates or you control — used for the join buttons
# - "id" must match the channel's actual chat_id (usually starts with -100)
# ============================================================

FORCE_JOIN_CHANNELS = [
    {
        "id": -1003998560024,
        "title": "Channel 1",
        "link": "https://t.me/+RsAsljvxgWZkNzg1",
    },
    {
        "id": -1004077604887,
        "title": "Channel 2",
        "link": "https://t.me/Il_Ravan_bhai_ll",
    },
]
