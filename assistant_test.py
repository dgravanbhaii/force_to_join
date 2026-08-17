import asyncio
from pyrogram import Client

import config


async def main():
    print("🔄 Connecting assistant...")

    app = Client(
        "dg_assistant",
        api_id=config.API_ID,
        api_hash=config.API_HASH,
        session_string=config.SESSION_STRING,
    )

    async with app:
        me = await app.get_me()

        print("✅ Assistant connected!")
        print(f"🆔 ID: {me.id}")
        print(f"👤 Name: {me.first_name or ''}")
        print(
            f"🔹 Username: @{me.username}"
            if me.username
            else "🔹 Username: None"
        )

        chat = await app.get_chat(config.TARGET_GROUP_USERNAME)

        print("✅ Target group found!")
        print(f"🏠 Title: {chat.title}")
        print(f"🆔 Chat ID: {chat.id}")
        print(f"👤 Type: {chat.type}")


if __name__ == "__main__":
    asyncio.run(main())
