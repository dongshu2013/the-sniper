import json
import logging

from redis import Redis
from telethon import events, types

# Initialize Redis connection
redis_client = Redis(host="localhost", port=6379, decode_responses=True)

MIN_PARTICIPANTS = 50

logger = logging.getLogger(__name__)


async def register_handlers(client):

    @client.on(events.NewMessage)
    async def handle_new_message(event):
        """Handle incoming messages from groups"""
        logger.info(f"New message received: {event.message.text}")
        if not event.is_group:
            return

        chat = await event.get_chat()
        enabled = redis_client.get(f"chat:{chat.id}:enabled")
        if enabled == "true":
            chat_id = str(event.chat_id)
            message_text = event.message.text

            logger.info(f"New group message received in {chat_id}: {message_text}")

            # Add message to the group-specific Redis queue
            queue_key = f"chat:{chat_id}:messages"
            redis_client.lpush(queue_key, message_text)

    @client.on(events.ChatAction)
    async def handle_group_join(event):
        """Handle bot joining a group"""
        # Check if this bot was added to a group
        if not event.is_group:
            return

        if event.user_added or event.user_joined:
            me = await client.get_me()
            if event.user_id != me.id:
                return

        chat = await event.get_chat()
        chat_id = str(chat.id)

        try:
            # Get all participants
            participants_count = await event.client.get_participants_count(chat)
            redis_client.set(
                f"chat:{chat_id}:enabled", participants_count >= MIN_PARTICIPANTS
            )
            if participants_count < MIN_PARTICIPANTS:
                return

            participants = await event.client.get_participants(chat)

            # Create a pipeline for batch Redis operations
            pipe = redis_client.pipeline()

            # Create set key for all members in this chat
            members_set_key = f"chat:{chat_id}:member_ids"
            pipe.delete(members_set_key)  # Clear existing set

            for user in participants:
                # Add member ID to the set of all chat members
                pipe.sadd(members_set_key, user.id)

                # Store individual member details
                member_key = f"chat:{chat_id}:member:{user.id}"
                member_info = {
                    "id": user.id,
                    "username": user.username,
                    "bot": user.bot,
                    "is_admin": isinstance(
                        user.participant, types.ChannelParticipantAdmin
                    ),
                }
                pipe.set(member_key, json.dumps(member_info))

            # Execute all Redis commands in pipeline
            pipe.execute()

        except Exception as e:
            logger.error(f"Error processing group join for {chat_id}: {str(e)}")
