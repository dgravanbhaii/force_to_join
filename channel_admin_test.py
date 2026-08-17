import asyncio
from pyrogram import Client
from pyrogram.raw.functions.channels import GetParticipants
from pyrogram.raw.types import ChannelParticipantsAdmins

import config


async def main():
    channel = "@ll_Telegram_Mafia_Fighterz_ll"

    app = Client(
        "dg_assistant",
        api_id=config.API_ID,
        api_hash=config.API_HASH,
        session_string=config.SESSION_STRING,
    )

    async with app:
        peer = await app.resolve_peer(channel)

        result = await app.invoke(
            GetParticipants(
                channel=peer,
                filter=ChannelParticipantsAdmins(),
                offset=0,
                limit=100,
                hash=0,
            )
        )

        print("ADMINS FOUND:", len(result.users))

        for user in result.users:
            print(
                f"ID={user.id} "
                f"username=@{user.username or 'None'} "
                f"name={user.first_name or ''} {user.last_name or ''}"
            )


if __name__ == "__main__":
    asyncio.run(main())
