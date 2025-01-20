import asyncio
import imghdr
import json
import logging
import os
import time
from datetime import datetime, timedelta
from typing import Optional

import asyncpg
from telethon import TelegramClient
from telethon.tl.functions.channels import GetFullChannelRequest
from telethon.tl.functions.messages import GetFullChatRequest
from telethon.tl.types import (
    ChannelParticipantsAdmins,
    InputMessagesFilterPinned,
    Message,
)

from src.common.config import DATABASE_URL
from src.common.r2_client import upload_file
from src.common.types import AccountChatStatus, ChatPhoto, ChatStatus
from src.common.utils import normalize_chat_id
from src.helpers.message_helper import should_process, store_messages, to_chat_message
from src.processors.processor import ProcessorBase

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Constants
NO_INITIAL_MESSAGES_ID = "no_initial_messages"
PERMISSION_DENIED_ADMIN_ID = "permission_denied"
GROUP_UPDATE_INTERVAL = 3600


class GroupProcessor(ProcessorBase):
    def __init__(self, client: TelegramClient):
        super().__init__(interval=3600)
        self.client = client
        self.pg_conn = None

    async def process(self):
        if not self.pg_conn:
            self.pg_conn = await asyncpg.connect(DATABASE_URL)

        dialogs = await self.get_all_dialogs()
        chat_ids = [normalize_chat_id(dialog.id) for dialog in dialogs]
        chat_info_map = await self.get_all_chat_metadata(chat_ids)
        logger.info(f"loaded {len(chat_info_map)} group metadata")

        # update account chat map
        me = await self.client.get_me()
        logger.info(f"updating account chat map for {me.id}")
        await self.update_account_chat_map(str(me.id), chat_ids)
        logger.info(f"updated account chat map for {me.id}")

        logger.info(f"updating {len(chat_ids)} groups for {me.username}")
        for chat_id, dialog in zip(chat_ids, dialogs):
            if not dialog.is_group and not dialog.is_channel:
                continue

            chat_info = chat_info_map.get(
                chat_id,
                {
                    "status": ChatStatus.EVALUATING.value,
                    "admins": [],
                    "pinned_messages": [],
                    "photo": None,
                    "updated_at": datetime.now() - timedelta(hours=2),
                },
            )

            updated_at_epoch = int(
                chat_info.get("updated_at", datetime.now()).timestamp()
            )
            if updated_at_epoch > int(time.time()) - GROUP_UPDATE_INTERVAL:
                logger.info(
                    f"skipping group {dialog.name} because it was updated recently"
                )
                continue

            logger.info(f"processing group {dialog.name}")
            status = chat_info.get("status", ChatStatus.EVALUATING.value)
            if status == ChatStatus.BLOCKED.value:
                logger.info(f"skipping blocked or low quality group {dialog.name}")
                continue

            # 1. Get group description
            logger.info("Getting group description...")
            description = await self.get_group_description(dialog)
            logger.info(f"group description: {description}")

            # 2. update photo
            logger.info("Updating photo...")
            photo = chat_info.get("photo", None)
            photo = ChatPhoto.model_validate_json(photo) if photo else None
            photo = await self.get_group_photo(dialog, photo)

            # 3. get pinned messages
            logger.info("Getting pinned messages...")
            pinned_message_ids = await self.get_pinned_messages(dialog)
            logger.info(f"pinned messages: {pinned_message_ids}")

            # 4. get initial messages
            logger.info("Getting initial messages...")
            initial_message_ids = chat_info.get("initial_messages", [])
            if not initial_message_ids:
                initial_message_ids = await self.get_initial_messages(dialog)
                logger.info(f"initial messages: {initial_message_ids}")

            # 5. get admins
            logger.info("Getting admins...")
            admins = chat_info.get("admins", [])
            if admins and admins[0] == PERMISSION_DENIED_ADMIN_ID:
                logger.info(f"admin permission denied for {dialog.name}, skipping...")
            else:
                admins = await self.get_admins(dialog)
                logger.info(f"admins: {admins}")

            logger.info(f"updating metadata for {chat_id}: {dialog.name}")
            await self._update_metadata(
                (
                    chat_id,
                    dialog.name or None,
                    description or None,
                    getattr(dialog.entity, "username", None),
                    getattr(dialog.entity, "participants_count", 0),
                    photo.model_dump_json() if photo else None,
                    json.dumps(pinned_message_ids),
                    json.dumps(admins),
                )
            )
            await asyncio.sleep(1)

    async def store_unprocessed_messages(
        self, chat_id: str, messages: list[Optional[Message]]
    ):
        message_ids = [str(msg.id) for msg in messages if should_process(msg)]
        existing_messages = await self.pg_conn.fetch(
            """
            SELECT message_id
            FROM chat_messages
            WHERE chat_id = $1 AND message_id = ANY($2)
            """,
            chat_id,
            message_ids,
        )
        existing_message_ids = {row["message_id"] for row in existing_messages}
        messages_to_insert = [
            to_chat_message(msg)
            for msg in messages
            if msg.id not in existing_message_ids
        ]
        if messages_to_insert:
            await store_messages(self.pg_conn, messages_to_insert)
        return message_ids

    async def get_initial_messages(self, dialog: any) -> list[str]:
        messages = await self.client.get_messages(
            dialog.entity,
            limit=10,
        )
        messages = [m for m in messages if m and should_process(m)]
        if not messages:
            return [NO_INITIAL_MESSAGES_ID]
        return await self.store_unprocessed_messages(
            normalize_chat_id(dialog.entity.id), messages
        )

    async def get_pinned_messages(self, dialog: any) -> list[str]:
        pinned_messages = await self.client.get_messages(
            dialog.entity,
            filter=InputMessagesFilterPinned,
            limit=50,
        )
        return await self.store_unprocessed_messages(
            normalize_chat_id(dialog.entity.id), pinned_messages
        )

    async def get_admins(self, dialog: any) -> list[str]:
        try:
            admins = await self.client.get_participants(
                dialog.entity, filter=ChannelParticipantsAdmins
            )
            return [str(admin.id) for admin in admins]
        except Exception as e:
            logger.error(f"Failed to get admins: {e}")
            return [PERMISSION_DENIED_ADMIN_ID]

    async def get_group_description(self, dialog: any) -> str:
        if dialog.is_channel:
            result = await self.client(GetFullChannelRequest(channel=dialog.entity))
            return result.full_chat.about or ""
        else:
            result = await self.client(GetFullChatRequest(chat_id=dialog.entity.id))
            return result.full_chat.about or ""

    async def get_group_photo(
        self, dialog: any, photo: ChatPhoto | None
    ) -> Optional[ChatPhoto]:
        new_photo = getattr(dialog.entity, "photo", {})
        logger.info(f"current photo: {new_photo}")
        if not new_photo:
            return None

        # could be ChatPhotoEmpty which doesn't have photo field
        photo_id = getattr(new_photo, "photo_id", None)
        if not photo_id:
            return None

        # got new photo
        if not photo or str(photo_id) != str(photo.id):
            local_photo_path = await self.client.download_profile_photo(
                dialog.entity, file=f"temp_photo_{new_photo.photo_id}"
            )
            if local_photo_path:
                logger.info(f"local photo path: {local_photo_path}")
                extension = await self._get_photo_extension(local_photo_path)
                photo_path = f"photos/{new_photo.photo_id}{extension}"
                upload_file(local_photo_path, photo_path)
                try:
                    os.remove(local_photo_path)
                except Exception as e:
                    logger.error(f"Failed to remove local photo: {e}")
                photo = ChatPhoto(id=str(new_photo.photo_id), path=photo_path)
        return photo

    async def get_all_dialogs(self):
        dialogs = []
        async for dialog in self.client.iter_dialogs(ignore_migrated=True):
            if not dialog.is_group and not dialog.is_channel:
                continue
            dialogs.append(dialog)
        return dialogs

    async def get_all_chat_metadata(self, chat_ids: list[str]) -> dict:
        rows = await self.pg_conn.fetch(
            """
            SELECT chat_id, status, admins, photo, initial_messages, updated_at
            FROM chat_metadata WHERE chat_id = ANY($1)
            """,
            chat_ids,
        )
        return {
            row["chat_id"]: {
                "status": row["status"],
                "admins": json.loads(row["admins"]),
                "photo": row["photo"],
                "initial_messages": json.loads(row["initial_messages"]),
                "updated_at": row["updated_at"],
            }
            for row in rows
        }

    async def _update_metadata(self, update: tuple):
        """Update chat metadata."""
        try:
            (
                chat_id,
                name,
                about,
                username,
                participants_count,
                photo,
                pinned_messages,
                admins,
            ) = update
            await self.pg_conn.execute(
                """
                INSERT INTO chat_metadata (
                    chat_id, name, about, username, participants_count,
                    pinned_messages, photo, admins, updated_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, CURRENT_TIMESTAMP)
                ON CONFLICT (chat_id) DO UPDATE SET
                    name = EXCLUDED.name,
                    about = EXCLUDED.about,
                    username = EXCLUDED.username,
                    participants_count = EXCLUDED.participants_count,
                    pinned_messages = EXCLUDED.pinned_messages,
                    updated_at = CURRENT_TIMESTAMP,
                    photo = EXCLUDED.photo,
                    admins = EXCLUDED.admins
                """,
                chat_id,
                name,
                about,
                username,
                participants_count,
                pinned_messages,
                photo,
                admins,
            )
        except Exception as e:
            logger.error(f"Failed to update metadata: {e}")

    async def update_account_chat_map(self, account_id: str, chat_ids: list[str]):
        async with self.pg_conn.transaction():
            # Insert or update all chat_ids for this account
            await self.pg_conn.executemany(
                """
                INSERT INTO account_chat (account_id, chat_id, status)
                VALUES ($1, $2, $3)
                ON CONFLICT (account_id, chat_id) DO UPDATE SET status = $3
                """,
                [
                    (account_id, chat_id, AccountChatStatus.WATCHING.value)
                    for chat_id in chat_ids
                ],
            )

            # Update status to QUIT for chats not in the list
            await self.pg_conn.execute(
                """
                UPDATE account_chat
                SET status = $1
                WHERE account_id = $2
                AND chat_id != ALL($3)
                """,
                AccountChatStatus.QUIT.value,
                account_id,
                chat_ids,
            )

    async def _get_photo_extension(self, file_path: str) -> str:
        """Detect the file extension of the downloaded photo."""
        try:
            img_type = imghdr.what(file_path)
            if img_type:
                return f".{img_type}"
        except Exception as e:
            logger.error(f"Failed to get photo extension: {e}")
        return ".jpg"
