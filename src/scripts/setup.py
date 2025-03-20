import os
import json
import logging
import asyncio
import time
import re
import requests
import imghdr
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from telethon.tl.functions.messages import GetDialogsRequest
from telethon.tl.functions.channels import GetFullChannelRequest
from telethon.tl.functions.messages import GetFullChatRequest
from telethon.tl.types import InputPeerEmpty

# Import the upload_file function from R2 client
from src.common.r2_client import upload_file

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
        
        # Dialog sync limit - 设置为None如果配置为0
        dialog_limit_config = self.config.get('dialog_limit', 100)
        self.dialog_limit = None if dialog_limit_config == 0 else dialog_limit_config
        
        # Message sync limit - 设置为None如果配置为0
        message_limit_config = self.config.get('message_limit', 100)
        self.message_limit = None if message_limit_config == 0 else message_limit_config
        
        # Initialize client
        self.client = None
        
        logger.info(f"Using session name: {self.session_name}")
        logger.info(f"Dialog limit: {self.dialog_limit}, Message limit: {self.message_limit}")

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

    async def get_group_description(self, dialog_entity):
        """Get the description (about) of a group or channel"""
        try:
            if hasattr(dialog_entity, 'broadcast') or hasattr(dialog_entity, 'megagroup'):
                # This is a channel or megagroup
                result = await self.client(GetFullChannelRequest(channel=dialog_entity))
                return result.full_chat.about or ""
            else:
                # This is a regular group
                result = await self.client(GetFullChatRequest(chat_id=dialog_entity.id))
                return result.full_chat.about or ""
        except Exception as e:
            logger.error(f"Failed to get group description: {e}")
            return ""

    async def _get_photo_extension(self, file_path):
        """Detect the file extension of the downloaded photo."""
        try:
            img_type = imghdr.what(file_path)
            if img_type:
                return f".{img_type}"
        except Exception as e:
            logger.error(f"Failed to get photo extension: {e}")
        return ".jpg"

    async def get_group_photo(self, dialog_entity):
        """Get the profile photo of a group or channel"""
        try:
            new_photo = getattr(dialog_entity, 'photo', {})
            if not new_photo:
                return None

            # Could be ChatPhotoEmpty which doesn't have photo field
            photo_id = getattr(new_photo, 'photo_id', None)
            if not photo_id:
                return None
                
            # Download the photo
            temp_photo_path = f"temp_photo_{photo_id}"
            local_photo_path = await self.client.download_profile_photo(
                dialog_entity, file=temp_photo_path
            )
            
            if local_photo_path:
                extension = await self._get_photo_extension(local_photo_path)
                photo_path = f"photos/{photo_id}{extension}"
                
                # Upload the photo to R2 storage
                upload_file(local_photo_path, photo_path)
                
                # Clean up the temporary file
                try:
                    os.remove(local_photo_path)
                except Exception as e:
                    logger.error(f"Failed to remove local photo: {e}")
                
                return {
                    "id": str(photo_id),
                    "path": photo_path
                }
            
        except Exception as e:
            logger.error(f"Failed to get group photo: {e}")
        
        return None

    async def get_participants_count(self, dialog_entity):
        """Get the number of participants in a group or channel"""
        try:
            if hasattr(dialog_entity, 'megagroup') or hasattr(dialog_entity, 'broadcast'):
                # This is a supergroup or channel
                full_channel = await self.client(GetFullChannelRequest(channel=dialog_entity))
                return full_channel.full_chat.participants_count
            elif hasattr(dialog_entity, 'chat_id'):
                # This is a regular group
                full_chat = await self.client(GetFullChatRequest(chat_id=dialog_entity.chat_id))
                return len(full_chat.users)
            else:
                # Try to use the attribute directly
                return getattr(dialog_entity, 'participants_count', 0)
        except Exception as e:
            logger.error(f"Failed to get participants count: {e}")
            return 0

    async def get_groups(self):
        """Get all dialogs (chats, groups, channels)"""
        groups = []
        
        # 使用iter_dialogs代替GetDialogsRequest，可以更好地支持无限获取
        # 类似于group_processor.py中的实现
        async for dialog in self.client.iter_dialogs(ignore_migrated=True):
            # 限制对话数量，如果有设置的话
            if self.dialog_limit is not None and len(groups) >= self.dialog_limit:
                break
            
            # 获取实体
            entity = dialog.entity
            
            # 仅处理组和频道（有标题的对话）
            if hasattr(entity, 'title'):  # Groups/channels have titles
                try:
                    # Get chat ID
                    chat_id = str(entity.id)
                    
                    # Get group description
                    about = await self.get_group_description(entity)
                    
                    # Get group photo
                    photo_data = await self.get_group_photo(entity)
                    photo_url = photo_data.get('path') if photo_data else None
                    
                    # Get participants count
                    participants_count = await self.get_participants_count(entity)
                    
                    # Determine if it's a channel
                    is_channel = hasattr(entity, 'broadcast') and entity.broadcast
                    
                    group_data = {
                        "chat_id": chat_id,
                        "title": entity.title,
                        "username": getattr(entity, 'username', None),
                        "photo_url": photo_url,
                        "about": about,
                        "participants_count": participants_count,
                        "is_channel": is_channel
                    }
                    
                    groups.append(group_data)
                    
                except Exception as e:
                    logger.error(f"Error processing group {getattr(entity, 'title', 'Unknown')}: {e}")
                    continue
        
        limit_info = f" (limited to {self.dialog_limit})" if self.dialog_limit is not None else " (unlimited)"
        logger.info(f"Found {len(groups)} groups/channels{limit_info}")
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
            
            limit_info = f" (limited to {limit})" if limit is not None else ""
            logger.info(f"Retrieved {len(messages)} messages from {chat_entity.title}{limit_info}")
        except Exception as e:
            logger.error(f"Error getting messages from {chat_entity.title}: {e}")
        
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
                    "participantsCount": group["participants_count"],
                    "isChannel": group["is_channel"]
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