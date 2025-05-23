import os
import json
import yaml
import logging
import logging.handlers
import asyncio
import time
import re
import requests
import imghdr
import boto3
from botocore.config import Config
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError, FloodWaitError, ServerError
from telethon.tl.functions.messages import GetDialogsRequest
from telethon.tl.functions.channels import GetFullChannelRequest
from telethon.tl.functions.messages import GetFullChatRequest
from telethon.tl.types import InputPeerEmpty

# R2 configuration
R2_ENDPOINT = "https://ecfd5a3d56c932e006ece0935c071e19.r2.cloudflarestorage.com"
R2_ACCESS_KEY_ID = "dd53d7a11683c30cce658b7a662e1a06"
R2_SECRET_ACCESS_KEY = "af586f2fc98bd7d18b82e16b6e7dd73d855cbecf914fec2b1bcefbf6d98b52b8"
R2_BUCKET_NAME = "the-sniper"

# Setup R2 client
s3 = boto3.client(
    service_name="s3",
    endpoint_url=R2_ENDPOINT,
    aws_access_key_id=R2_ACCESS_KEY_ID,
    aws_secret_access_key=R2_SECRET_ACCESS_KEY,
    region_name="auto",
    config=Config(
        s3={"addressing_style": "virtual"},
        signature_version="s3v4",
        retries={"max_attempts": 3},
    ),
)

# R2 functions
def upload_file(file_path: str, key: str):
    try:
        s3.upload_file(file_path, R2_BUCKET_NAME, key)
        return key
    except Exception as e:
        logger.error(f"Failed to upload file to R2: {e}")
        return None

# Configure logging
def setup_logging():
    # Create logs directory if it doesn't exist
    os.makedirs("logs", exist_ok=True)
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    
    # Console handler for immediate feedback
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_format = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    console_handler.setFormatter(console_format)
    root_logger.addHandler(console_handler)
    
    # File handlers for persistent logs
    info_handler = logging.handlers.RotatingFileHandler(
        "logs/telegram-sync.log", 
        maxBytes=10*1024*1024,  # 10MB
        backupCount=5
    )
    info_handler.setLevel(logging.INFO)
    info_format = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    info_handler.setFormatter(info_format)
    
    error_handler = logging.handlers.RotatingFileHandler(
        "logs/telegram-sync-error.log", 
        maxBytes=10*1024*1024,  # 10MB
        backupCount=5
    )
    error_handler.setLevel(logging.ERROR)
    error_format = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    error_handler.setFormatter(error_format)
    
    root_logger.addHandler(info_handler)
    root_logger.addHandler(error_handler)
    
    # Filter out excessive Telethon download logs
    telethon_downloads_logger = logging.getLogger('telethon.client.downloads')
    telethon_downloads_logger.setLevel(logging.WARNING)
    
    return logging.getLogger(__name__)

# Setup logging
logger = setup_logging()

class TelegramSyncClient:
    def __init__(self, config, account_config):
        # Store base configuration
        self.api_base_url = config.get('api_base_url', 'http://localhost:3000/api')
        self.api_key = config.get('api_key')
        
        # Telegram API credentials from account config
        self.api_id = account_config.get('telegram_api_id')
        self.api_hash = account_config.get('telegram_api_hash')
        self.phone = account_config.get('telegram_phone')
        
        # Create session name from phone number and timestamp
        timestamp = int(time.time())
        # Clean phone number for use as filename (remove +, spaces, etc)
        clean_phone = re.sub(r'[^0-9]', '', self.phone)
        self.session_name = f"{clean_phone}_{timestamp}"
        
        # Dialog sync limit - 设置为None如果配置为0
        dialog_limit_config = account_config.get('dialog_limit', 100)
        self.dialog_limit = None if dialog_limit_config == 0 else dialog_limit_config
        
        # Message sync limit - 设置为None如果配置为0
        message_limit_config = account_config.get('message_limit', 100)
        self.message_limit = None if message_limit_config == 0 else message_limit_config
        
        # Initialize client
        self.client = None
        
        # Configure timeouts and connection settings
        self.connection_retries = 3
        self.connection_timeout = 30  # seconds
        self.operation_timeout = 300  # seconds for operations
        
        # Last successful sync timestamp
        self.last_sync_time = 0
        
        logger.info(f"Initialized TelegramSyncClient for phone: {self.phone}")
        logger.info(f"Dialog limit: {self.dialog_limit}, Message limit: {self.message_limit}")

    async def connect(self):
        """Connect to Telegram and ensure authorization"""
        # 使用基于手机号的会话名称以便区分多个账号
        clean_phone = re.sub(r'[^0-9]', '', self.phone)
        session_file = f"telegram_session_{clean_phone}"
        self.client = TelegramClient(
            session_file, 
            self.api_id, 
            self.api_hash,
            connection_retries=self.connection_retries,
            request_retries=self.connection_retries
        )
        
        # 增加重试逻辑和连接超时
        retry_count = self.connection_retries
        for attempt in range(retry_count):
            try:
                logger.info(f"Connecting to Telegram (attempt {attempt+1}/{retry_count}) for {self.phone}")
                await asyncio.wait_for(
                    self.client.connect(),
                    timeout=self.connection_timeout
                )
                logger.info(f"Connection successful for {self.phone}")
                break
            except asyncio.TimeoutError:
                if attempt < retry_count - 1:
                    logger.warning(f"Connection timeout for {self.phone} (attempt {attempt+1}). Retrying in 5 seconds...")
                    await asyncio.sleep(5)
                else:
                    logger.error(f"Connection failed after {retry_count} attempts for {self.phone}: Timeout")
                    raise
            except Exception as e:
                if attempt < retry_count - 1:
                    logger.warning(f"Connection attempt {attempt+1} failed for {self.phone}: {e}. Retrying in 5 seconds...")
                    await asyncio.sleep(5)
                else:
                    logger.error(f"Connection failed after {retry_count} attempts for {self.phone}: {e}")
                    raise
        
        # Check if already authorized
        is_authorized = False
        try:
            is_authorized = await asyncio.wait_for(
                self.client.is_user_authorized(),
                timeout=self.connection_timeout
            )
        except Exception as e:
            logger.error(f"Error checking authorization for {self.phone}: {e}")
            raise
            
        if not is_authorized:
            # 在自动运行模式下，无法请求验证码，记录错误并退出
            if os.environ.get('AUTOMATED_RUN') == 'true':
                logger.error(f"Session is not authorized for {self.phone}. Please run the script manually first to generate a valid session.")
                return None
            
            # 交互式模式下请求验证码
            await self.client.send_code_request(self.phone)
            try:
                code = input(f'Enter the code received on {self.phone}: ')
                await self.client.sign_in(self.phone, code)
            except SessionPasswordNeededError:
                password = input('Two-step verification enabled. Please enter your password: ')
                await self.client.sign_in(password=password)
        
        logger.info(f"Successfully connected to Telegram with phone: {self.phone}")
        return self.client

    async def get_group_description(self, dialog_entity):
        """Get the description (about) of a group or channel"""
        try:
            if hasattr(dialog_entity, 'broadcast') or hasattr(dialog_entity, 'megagroup'):
                # This is a channel or megagroup
                result = await asyncio.wait_for(
                    self.client(GetFullChannelRequest(channel=dialog_entity)),
                    timeout=self.operation_timeout
                )
                return result.full_chat.about or ""
            else:
                # This is a regular group
                result = await asyncio.wait_for(
                    self.client(GetFullChatRequest(chat_id=dialog_entity.id)),
                    timeout=self.operation_timeout
                )
                return result.full_chat.about or ""
        except asyncio.TimeoutError:
            logger.error(f"Timeout getting group description for {getattr(dialog_entity, 'title', 'Unknown')}")
            return ""
        except Exception as e:
            logger.error(f"Failed to get group description for {getattr(dialog_entity, 'title', 'Unknown')}: {e}")
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
            local_photo_path = await asyncio.wait_for(
                self.client.download_profile_photo(
                    dialog_entity, file=temp_photo_path
                ),
                timeout=self.operation_timeout
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
            
        except asyncio.TimeoutError:
            logger.error(f"Timeout downloading group photo for {getattr(dialog_entity, 'title', 'Unknown')}")
        except Exception as e:
            logger.error(f"Failed to get group photo for {getattr(dialog_entity, 'title', 'Unknown')}: {e}")
        
        return None

    async def get_participants_count(self, dialog_entity):
        """Get the number of participants in a group or channel"""
        try:
            if hasattr(dialog_entity, 'megagroup') or hasattr(dialog_entity, 'broadcast'):
                # This is a supergroup or channel
                full_channel = await asyncio.wait_for(
                    self.client(GetFullChannelRequest(channel=dialog_entity)),
                    timeout=self.operation_timeout
                )
                return full_channel.full_chat.participants_count
            elif hasattr(dialog_entity, 'chat_id'):
                # This is a regular group
                full_chat = await asyncio.wait_for(
                    self.client(GetFullChatRequest(chat_id=dialog_entity.chat_id)),
                    timeout=self.operation_timeout
                )
                return len(full_chat.users)
            else:
                # Try to use the attribute directly
                return getattr(dialog_entity, 'participants_count', 0)
        except asyncio.TimeoutError:
            logger.error(f"Timeout getting participants count for {getattr(dialog_entity, 'title', 'Unknown')}")
            return 0
        except Exception as e:
            logger.error(f"Failed to get participants count for {getattr(dialog_entity, 'title', 'Unknown')}: {e}")
            return 0

    async def get_groups(self):
        """Get all dialogs (chats, groups, channels)"""
        groups = []
        
        try:
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
        except FloodWaitError as e:
            # Handle rate limiting
            wait_time = e.seconds
            logger.warning(f"Hit Telegram rate limit. Need to wait {wait_time} seconds.")
            await asyncio.sleep(wait_time)
            # Return what we've got so far
            logger.info(f"Continuing after FloodWaitError with {len(groups)} groups collected")
        except Exception as e:
            logger.error(f"Error getting dialogs for {self.phone}: {e}")
            # Still return what we've collected
        
        limit_info = f" (limited to {self.dialog_limit})" if self.dialog_limit is not None else " (unlimited)"
        logger.info(f"Found {len(groups)} groups/channels{limit_info}")
        return groups

    async def get_messages(self, chat_entity, limit=None):
        """Get messages from a specific chat/group/channel"""
        if limit is None:
            limit = self.message_limit
            
        messages = []
        try:
            message_count = 0
            async for message in self.client.iter_messages(chat_entity, limit=limit):
                message_count += 1
                  
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
            
            # limit_info = f" (limited to {limit})" if limit is not None else ""
            # logger.info(f"Retrieved {len(messages)} messages from {chat_entity.title}{limit_info}")
            
        except FloodWaitError as e:
            # Handle rate limiting
            wait_time = e.seconds
            logger.warning(f"Hit Telegram rate limit while fetching messages. Need to wait {wait_time} seconds.")
            await asyncio.sleep(wait_time)
            # Return what we've got so far
            logger.info(f"Continuing after FloodWaitError with {len(messages)} messages collected from {chat_entity.title}")
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
            logger.info(f"Syncing {len(channels_data)} channels to API")
            response = requests.post(
                f"{self.api_base_url}/channels",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"{self.api_key}" if self.api_key else ""
                },
                json=channels_data,
                timeout=60  # 60 second timeout
            )
            response.raise_for_status()
            result = response.json()
            
            logger.info(f"Successfully synced {len(result.get('data', {}).get('channel_id', []))} channels")
            return result.get('data', {}).get('channel_id', [])
            
        except requests.exceptions.Timeout:
            logger.error(f"API request timed out when syncing channels")
            return []
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
            # logger.info(f"Syncing {len(messages_data)} messages for channel {channel_id}")
            response = requests.post(
                f"{self.api_base_url}/messages/batch",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"{self.api_key}" if self.api_key else ""
                },
                json=request_body,
                timeout=120  # Increased timeout for large message batches
            )
            response.raise_for_status()
            result = response.json()
            
            synced_count = result.get('data', {}).get('synced_message_count', 0)
            logger.info(f"Successfully synced {synced_count} messages for channel {channel_id}")
            return synced_count
            
        except requests.exceptions.Timeout:
            logger.error(f"API request timed out when syncing messages for channel {channel_id}")
            return 0
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to sync messages for channel {channel_id}: {e}")
            if hasattr(e, 'response') and e.response:
                logger.error(f"Response: {e.response.text}")
            return 0

    async def sync_all(self):
        """Sync all groups and their messages"""
        # Connect to Telegram
        try:
            await self.connect()
        except Exception as e:
            logger.error(f"Failed to connect to Telegram for {self.phone}: {e}")
            return {
                "phone": self.phone,
                "channels_synced": 0,
                "messages_synced": 0,
                "success": False,
                "error": str(e)
            }
        
        # 开始计时
        start_time = time.time()
        
        # 先设置心跳日志
        heartbeat_task = asyncio.create_task(self._heartbeat_log())
        
        try:
            # Get all groups
            logger.info(f"Fetching groups for {self.phone}")
            groups = await self.get_groups()
            
            # Sync groups to API
            logger.info(f"Syncing groups to API for {self.phone}")
            channel_ids = self.sync_channels_to_api(groups)
            
            total_messages_synced = 0
            
            # For each group, get and sync messages
            for i, channel_id in enumerate(channel_ids):
                if i >= len(groups):
                    logger.warning(f"Index mismatch: channel_id {channel_id} has no corresponding group")
                    continue
                    
                group = groups[i]
                
                try:
                    logger.info(f"Processing group {i+1}/{len(channel_ids)}: {group['title']}")
                    
                    # Get the entity from chat_id
                    entity = await self.client.get_entity(int(group["chat_id"]))
                    
                    # Get messages from this group
                    messages = await self.get_messages(entity)
                    
                    # Sync messages to API
                    messages_synced = self.sync_messages_to_api(channel_id, messages)
                    total_messages_synced += messages_synced
                    
                except FloodWaitError as e:
                    # Handle rate limiting
                    wait_time = e.seconds
                    logger.warning(f"Hit Telegram rate limit while processing group {group['title']}. Need to wait {wait_time} seconds.")
                    await asyncio.sleep(wait_time)
                    logger.info(f"Continuing after FloodWaitError for group {group['title']}")
                except Exception as e:
                    logger.error(f"Error processing group {group['title']}: {e}")
                    continue
            
            # Update last sync time
            self.last_sync_time = time.time()
            elapsed_time = self.last_sync_time - start_time
            
            logger.info(f"Sync complete for {self.phone}. Total messages synced: {total_messages_synced}. Time elapsed: {elapsed_time:.2f} seconds")
            
            return {
                "phone": self.phone,
                "channels_synced": len(channel_ids),
                "messages_synced": total_messages_synced,
                "success": True,
                "elapsed_time": elapsed_time
            }
        except Exception as e:
            logger.error(f"Error during sync for {self.phone}: {e}")
            return {
                "phone": self.phone,
                "channels_synced": 0,
                "messages_synced": 0,
                "success": False,
                "error": str(e)
            }
        finally:
            # Cancel heartbeat task
            heartbeat_task.cancel()
            
            # 断开连接
            try:
                await self.client.disconnect()
                logger.info(f"Disconnected from Telegram for {self.phone}")
            except Exception as e:
                logger.error(f"Error disconnecting from Telegram for {self.phone}: {e}")

    async def _heartbeat_log(self):
        """Log a heartbeat message periodically to show the script is running"""
        try:
            while True:
                logger.info(f"Heartbeat: Sync for {self.phone} is running...")
                await asyncio.sleep(60)  # Log every minute
        except asyncio.CancelledError:
            # Task was cancelled - this is expected behavior
            pass
        except Exception as e:
            logger.error(f"Error in heartbeat logger: {e}")

def load_config(config_path):
    """Load configuration from YAML file"""
    try:
        with open(config_path, 'r') as f:
            if config_path.endswith('.json'):
                logger.warning("Using deprecated JSON config format. Please migrate to YAML.")
                return json.load(f)
            else:
                return yaml.safe_load(f)
    except FileNotFoundError:
        logger.error(f"Config file not found: {config_path}")
        raise
    except (json.JSONDecodeError, yaml.YAMLError) as e:
        logger.error(f"Invalid config file: {config_path}, Error: {e}")
        raise

async def run_sync_task():
    """Run the sync task once"""
    # Check if config path is provided as environment variable or use default
    config_path = os.environ.get('TELEGRAM_CONFIG_PATH', 'config.yaml')
    
    try:
        # Log script start
        logger.info(f"Starting Telegram sync task with config: {config_path}")
        
        # Load the configuration
        config = load_config(config_path)
        
        # Check if accounts are configured
        if 'accounts' not in config or not config['accounts']:
            logger.error("No Telegram accounts configured in config file")
            return
        
        # Process each account
        all_results = []
        for account_config in config['accounts']:
            phone = account_config.get('telegram_phone', 'Unknown')
            logger.info(f"Processing account: {phone}")
            
            # Initialize and run the sync client for this account
            client = TelegramSyncClient(config, account_config)
            try:
                result = await client.sync_all()
                all_results.append(result)
            except Exception as e:
                logger.error(f"Failed to sync account {phone}: {e}")
                all_results.append({
                    "phone": phone,
                    "channels_synced": 0,
                    "messages_synced": 0,
                    "success": False,
                    "error": str(e)
                })
        
        # Log overall summary
        successful_syncs = sum(1 for r in all_results if r.get('success', False))
        total_channels = sum(r.get('channels_synced', 0) for r in all_results)
        total_messages = sum(r.get('messages_synced', 0) for r in all_results)
        
        logger.info(f"Overall sync summary: {len(all_results)} accounts processed, {successful_syncs} successful")
        logger.info(f"Total channels synced: {total_channels}")
        logger.info(f"Total messages synced: {total_messages}")
        
        # Return success if at least one account was synced successfully
        return successful_syncs > 0
        
    except Exception as e:
        logger.error(f"Sync failed with error: {e}")
        return False

async def scheduled_task(interval_minutes=5):
    """Run the sync task every specified number of minutes"""
    logger.info(f"Starting scheduled task to run every {interval_minutes} minutes")
    
    # 设置自动运行环境变量，让连接函数知道是自动模式
    os.environ['AUTOMATED_RUN'] = 'true'
    
    consecutive_failures = 0
    
    while True:
        start_time = time.time()
        logger.info(f"Running scheduled sync at {time.strftime('%Y-%m-%d %H:%M:%S')}")
        
        try:
            success = await run_sync_task()
            if success:
                logger.info("Scheduled sync completed successfully")
                consecutive_failures = 0
            else:
                logger.error("Scheduled sync failed (no accounts synced successfully)")
                consecutive_failures += 1
        except Exception as e:
            logger.error(f"Scheduled sync failed with exception: {e}")
            consecutive_failures += 1
        
        # If we have too many consecutive failures, restart the client
        if consecutive_failures >= 3:
            logger.warning(f"Detected {consecutive_failures} consecutive failures. Attempting recovery...")
            
            # Add recovery logic here, such as clearing session files
            recovery_message = "No specific recovery action taken, continuing with next attempt"
            logger.info(f"Recovery attempt: {recovery_message}")
            
            # Reset the counter after a recovery attempt
            consecutive_failures = 0
        
        # Calculate sleep time to maintain exact interval
        elapsed = time.time() - start_time
        sleep_time = max(0, interval_minutes * 60 - elapsed)
        
        logger.info(f"Next sync scheduled in {sleep_time:.1f} seconds at {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time() + sleep_time))}")
        await asyncio.sleep(sleep_time)

async def main():
    """Main function to run the script"""
    import sys
    
    # Ensure logs directory exists
    os.makedirs("logs", exist_ok=True)
    
    # Create a symlink to the logs directory in /home/ec2-user
    if os.path.exists('/home/ec2-user'):
        try:
            if not os.path.exists('/home/ec2-user/telegram-sync.log'):
                os.symlink(os.path.abspath('logs/telegram-sync.log'), '/home/ec2-user/telegram-sync.log')
            if not os.path.exists('/home/ec2-user/telegram-sync-error.log'):
                os.symlink(os.path.abspath('logs/telegram-sync-error.log'), '/home/ec2-user/telegram-sync-error.log')
        except Exception as e:
            logger.warning(f"Could not create symlinks in /home/ec2-user: {e}")
    
    # Check if running in scheduled mode
    if len(sys.argv) > 1 and sys.argv[1] == '--scheduled':
        interval = 5  # Default to 5 minutes
        if len(sys.argv) > 2:
            try:
                interval = int(sys.argv[2])
            except ValueError:
                logger.warning(f"Invalid interval '{sys.argv[2]}', using default of 5 minutes")
        
        await scheduled_task(interval)
    else:
        # Run once (original behavior)
        if len(sys.argv) > 1:
            config_path = sys.argv[1]
            os.environ['TELEGRAM_CONFIG_PATH'] = config_path
        
        await run_sync_task()

if __name__ == "__main__":
    asyncio.run(main())