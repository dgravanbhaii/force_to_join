import asyncio
import sys

from pyrogram import Client
from pyrogram.errors import RPCError

import config


async def main():
    if len(sys.argv) != 2:
        print("Usage:")
        print("  python3 assistant_add_test.py USER_ID")
        print("  python3 assistant_add_test.py @username")
        return

    target = sys.argv[1].strip()

    if target.isdigit():
        target = int(target)

    print(f"🔄 Resolving user: {target}")

    app = Client(
        "dg_assistant",
        api_id=config.API_ID,
        api_hash=config.API_HASH,
        session_string=config.SESSION_STRING,
    )

    async with app:
        try:
            user = await app.get_users(target)

            print("✅ User resolved!")
            print(f"🆔 ID: {user.id}")
            print(f"👤 Name: {user.first_name or ''}")

            if user.username:
                print(f"🔹 Username: @{user.username}")
            else:
                print("🔹 Username: None")

            print("🔄 Trying direct add...")

            await app.add_chat_members(
                config.TARGET_GROUP_USERNAME,
                user.id,
            )

            print("✅ User added successfully!")

        except RPCError as e:
            print("❌ Telegram rejected the operation:")
            print(f"{type(e).__name__}: {e}")

        except Exception as e:
            print("❌ Unexpected error:")
            print(f"{type(e).__name__}: {e}")


if __name__ == "__main__":
    asyncio.run(main())
