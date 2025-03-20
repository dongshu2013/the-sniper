import os
import json
import logging
import asyncio
import time
import re
import requests
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from telethon.tl.functions.messages import GetDialogsRequest
from telethon.tl.types import InputPeerEmpty

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class TelegramSyncClient:
    def __init__(self, config_path='config.json'):
        # Load configuration
        self.config = self._load_config(config_path)
        self.api_base_url = self.config.get('api_base_url', 'http://localhost:3000/api')
        self.api_key = self.config.get('api_key')
        
        # Telegram API credentials
        self.api_id = self.config.get('telegram_api_id')
        self.api_hash = self.config.get('telegram_api_hash')
        self.phone = self.config.get('telegram_phone')
        
        # Create session name from phone number and timestamp
        timestamp = int(time.time())
        # Clean phone number for use as filename (remove +, spaces, etc)
        clean_phone = re.sub(r'[^0-9]', '', self.phone)
        self.session_name = f"{clean_phone}_{timestamp}"
        
        # Message sync limit
        self.message_limit = self.config.get('message_limit', 100)
        # Dialog sync limit (新增)
        self.dialog_limit = self.config.get('dialog_limit', 100)
        
        # Initialize client
        self.client = None
        
        logger.info(f"Using session name: {self.session_name}")

    def _load_config(self, config_path):
        """Load configuration from JSON file"""
        try:
            with open(config_path, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            logger.error(f"Config file not found: {config_path}")
            raise
        except json.JSONDecodeError:
            logger.error(f"Invalid JSON in config file: {config_path}")
            raise

    async def connect(self):
        """Connect to Telegram and ensure authorization"""
        # 改用固定会话名称而不是每次生成新的
        session_file = "telegram_session"
        self.client = TelegramClient(session_file, self.api_id, self.api_hash)
        
        # 增加重试逻辑和连接超时
        retry_count = 3
        for attempt in range(retry_count):
            try:
                await self.client.connect()
                break
            except Exception as e:
                if attempt < retry_count - 1:
                    logger.warning(f"Connection attempt {attempt+1} failed: {e}. Retrying in 5 seconds...")
                    await asyncio.sleep(5)
                else:
                    logger.error(f"Failed to connect after {retry_count} attempts: {e}")
                    raise
        
        # Check if already authorized
        if not await self.client.is_user_authorized():
            await self.client.send_code_request(self.phone)
            try:
                code = input('Enter the code you received: ')
                await self.client.sign_in(self.phone, code)
            except SessionPasswordNeededError:
                password = input('Two-step verification enabled. Please enter your password: ')
                await self.client.sign_in(password=password)
        
        logger.info("Successfully connected to Telegram")
        return self.client

    async def get_groups(self):
        """Get all dialogs (chats, groups, channels)"""
        result = await self.client(GetDialogsRequest(
            offset_date=None,
            offset_id=0,
            offset_peer=InputPeerEmpty(),
            limit=self.dialog_limit,
            hash=0
        ))
        
        # Filter for groups and channels only
        groups = []
        for dialog in result.dialogs:
            entity = await self.client.get_entity(dialog.peer)
            if hasattr(entity, 'title'):  # Groups/channels have titles
                try:
                    # Get additional info about the group
                    chat_id = str(entity.id)
                    photo_url = None
                    about = None
                    participants_count = None
                    
                    # Try to get chat photo if available
                    try:
                        if entity.photo:
                            photo = await self.client.download_profile_photo(entity, file=bytes)
                            if photo:
                                # In a real application, you might want to upload this somewhere
                                # and use the URL instead of raw bytes
                                photo_url = f"telegram_photo_{chat_id}"
                    except Exception as e:
                        logger.warning(f"Failed to get photo for group {entity.title}: {e}")
                    
                    # Try to get about/description
                    try:
                        full_chat = await self.client.get_entity(entity)
                        if hasattr(full_chat, 'about'):
                            about = full_chat.about
                    except Exception as e:
                        logger.warning(f"Failed to get about for group {entity.title}: {e}")
                    
                    # 正确获取参与者数量
                    try:
                        from telethon.tl.functions.channels import GetFullChannelRequest
                        from telethon.tl.functions.messages import GetFullChatRequest
                        
                        if hasattr(entity, 'megagroup') or hasattr(entity, 'broadcast'):
                            # 这是一个超级群组或频道
                            full_channel = await self.client(GetFullChannelRequest(channel=entity))
                            participants_count = full_channel.full_chat.participants_count
                        elif hasattr(entity, 'chat_id'):
                            # 这是一个普通群组
                            full_chat = await self.client(GetFullChatRequest(chat_id=entity.chat_id))
                            participants_count = len(full_chat.users)
                        else:
                            # 尝试直接使用属性（可能在某些情况下有效）
                            participants_count = getattr(entity, 'participants_count', 0)
                    except Exception as e:
                        logger.warning(f"Failed to get participants count for group {entity.title}: {e}")
                        participants_count = 0
                    
                    group_data = {
                        "chat_id": chat_id,
                        "title": entity.title,
                        "username": getattr(entity, 'username', None),
                        "photo_url": photo_url,
                        "about": about,
                        "participants_count": participants_count,
                        "is_channel": hasattr(entity, 'broadcast') and entity.broadcast
                    }
                    
                    groups.append(group_data)
                    
                    # 达到限制数量后退出
                    if len(groups) >= self.dialog_limit:
                        break
                    
                except Exception as e:
                    logger.error(f"Error processing group {getattr(entity, 'title', 'Unknown')}: {e}")
                    continue
        
        logger.info(f"Found {len(groups)} groups/channels (limited to {self.dialog_limit})")
        return groups

    async def get_messages(self, chat_entity, limit=None):
        """Get messages from a specific chat/group/channel"""
        if limit is None:
            limit = self.message_limit
            
        messages = []
        try:
            async for message in self.client.iter_messages(chat_entity, limit=limit):
                if not message.message:  # Skip messages without text
                    continue
                    
                # Extract message data
                message_data = {
                    "message_id": str(message.id),
                    "chat_id": str(chat_entity.id),
                    "message_text": message.message,
                    "message_timestamp": int(message.date.timestamp()),
                    "sender_id": str(message.sender_id) if message.sender_id else "",
                }
                
                # Add optional fields if they exist
                if message.reply_to:
                    if hasattr(message.reply_to, 'reply_to_msg_id'):
                        message_data["reply_to"] = str(message.reply_to.reply_to_msg_id)
                    if hasattr(message.reply_to, 'reply_to_top_id'):
                        message_data["topic_id"] = str(message.reply_to.reply_to_top_id)
                
                message_data["is_pinned"] = bool(message.pinned)
                
                # Handle media if present
                if message.media:
                    media_type = type(message.media).__name__.lower().replace('message', '')
                    message_data["media_type"] = media_type
                    
                    if hasattr(message.media, 'photo'):
                        message_data["media_file_id"] = str(message.media.photo.id)
                    elif hasattr(message.media, 'document'):
                        message_data["media_file_id"] = str(message.media.document.id)
                
                messages.append(message_data)
        except Exception as e:
            logger.error(f"Error getting messages from {chat_entity.title}: {e}")
        
        logger.info(f"Retrieved {len(messages)} messages from {chat_entity.title}")
        return messages

    def sync_channels_to_api(self, groups):
        """Sync groups/channels with the API endpoint"""
        if not groups:
            logger.warning("No groups to sync")
            return []
            
        # Prepare the data for API
        channels_data = []
        for group in groups:
            channel = {
                "channel_type": "telegram_group",
                "platform_id": group["chat_id"],
                "metadata": {
                    "name": group["title"],
                    "username": group["username"],
                    "about": group["about"],
                    "photo": group["photo_url"],
                    "participants_count": group["participants_count"],
                    "is_channel": group["is_channel"]
                },
                "is_public": True  # You might want to make this configurable
            }
            channels_data.append(channel)
        
        # Make the API request
        try:
            response = requests.post(
                f"{self.api_base_url}/channels",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"{self.api_key}" if self.api_key else ""
                },
                json=channels_data
            )
            response.raise_for_status()
            result = response.json()
            
            logger.info(f"Successfully synced {len(result.get('data', {}).get('channel_id', []))} channels")
            return result.get('data', {}).get('channel_id', [])
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to sync channels: {e}")
            if hasattr(e, 'response') and e.response:
                logger.error(f"Response: {e.response.text}")
            return []

    def sync_messages_to_api(self, channel_id, messages):
        """Sync messages with the API endpoint"""
        if not messages:
            logger.warning(f"No messages to sync for channel {channel_id}")
            return 0
            
        # 准备API请求数据 - 使用syncedMessages包装消息数组
        messages_data = []
        for msg in messages:
            message = {
                "channel_id": channel_id,
                "chat_id": msg["chat_id"],
                "message_id": msg["message_id"],
                "message_text": msg["message_text"],
                "message_timestamp": msg["message_timestamp"],
                "sender_id": msg.get("sender_id", ""),
                "is_pinned": msg.get("is_pinned", False)
            }
            
            # 添加可选字段
            if "reply_to" in msg:
                message["reply_to"] = msg["reply_to"]
            if "topic_id" in msg:
                message["topic_id"] = msg["topic_id"]
            if "media_type" in msg:
                message["media_type"] = msg["media_type"]
            if "media_file_id" in msg:
                message["media_file_id"] = msg["media_file_id"]
            
            messages_data.append(message)
        
        # 包装消息数据到syncedMessages字段中
        request_body = {
            "syncedMessages": messages_data
        }
        
        # 发送API请求
        try:
            response = requests.post(
                f"{self.api_base_url}/messages/batch",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"{self.api_key}" if self.api_key else ""
                },
                json=request_body
            )
            response.raise_for_status()
            result = response.json()
            
            logger.info(f"Successfully synced {result.get('data', {}).get('synced_message_count', 0)} messages")
            return result.get('data', {}).get('synced_message_count', 0)
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to sync messages: {e}")
            if hasattr(e, 'response') and e.response:
                logger.error(f"Response: {e.response.text}")
            return 0

    async def sync_all(self):
        """Sync all groups and their messages"""
        # Connect to Telegram
        await self.connect()
        
        # Get all groups
        groups = await self.get_groups()
        
        # Sync groups to API
        channel_ids = self.sync_channels_to_api(groups)
        
        total_messages_synced = 0
        
        # For each group, get and sync messages
        for i, channel_id in enumerate(channel_ids):
            group = groups[i]
            
            try:
                # Get the entity from chat_id
                entity = await self.client.get_entity(int(group["chat_id"]))
                
                # Get messages from this group
                messages = await self.get_messages(entity)
                
                # Sync messages to API
                messages_synced = self.sync_messages_to_api(channel_id, messages)
                total_messages_synced += messages_synced
                
            except Exception as e:
                logger.error(f"Error processing group {group['title']}: {e}")
                continue
        
        logger.info(f"Sync complete. Total messages synced: {total_messages_synced}")
        
        # Disconnect
        await self.client.disconnect()
        return {
            "channels_synced": len(channel_ids),
            "messages_synced": total_messages_synced
        }

async def main():
    """Main function to run the script"""
    # Check if config path is provided as argument
    import sys
    config_path = sys.argv[1] if len(sys.argv) > 1 else 'config.json'
    
    try:
        # Initialize and run the sync client
        client = TelegramSyncClient(config_path)
        result = await client.sync_all()
        
        logger.info(f"Sync summary: {json.dumps(result)}")
        
    except Exception as e:
        logger.error(f"Sync failed with error: {e}")
        raise

if __name__ == "__main__":
    asyncio.run(main())