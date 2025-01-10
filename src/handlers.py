from logging import logger

from telethon import events


async def register_handlers(client):

    @client.on(events.NewMessage)
    async def handle_new_message(event):
        """Handle incoming messages"""
        logger.info(f"New message received: {event.message.text}")
        # Add your message handling logic here
