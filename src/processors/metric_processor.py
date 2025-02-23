import asyncio
import json
import logging
import time
from typing import Dict, List, Optional, Tuple

import asyncpg

from src.common.agent_client import AgentClient
from src.common.config import DATABASE_URL
from src.common.types import ChatMessage, ChatMetadata
from src.common.utils import parse_ai_response
from src.helpers.message_helper import db_row_to_chat_message, gen_message_content
from src.processors.processor import ProcessorBase

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

class MetricProcessor(ProcessorBase):
    def __init__(self):
        super().__init__(interval=60)  # Check every minute
        self.batch_size = 20
        self.pg_pool = None
        self.agent_client = AgentClient()
        self.processing_ids = set()
        self.queue = asyncio.Queue()
        self.workers = []
        self.metric_definitions = {}
        # 添加测试模式数据限制
        self.is_testing = True
        self.test_limit = 2  # 测试时只处理2条数据

    async def prepare(self):
        self.pg_pool = await asyncpg.create_pool(
            DATABASE_URL, min_size=self.batch_size, max_size=self.batch_size
        )
        # Load metric definitions
        await self.load_metric_definitions()
        # Start worker tasks
        self.workers = [
            asyncio.create_task(self.process_chat_metrics())
            for _ in range(self.batch_size)
        ]
        logger.info(f"{self.__class__.__name__} processor initiated")

    async def load_metric_definitions(self):
        """
        Load metric definitions from database, organized by user_id
        return:
            {
                'user_id': {
                    'metric_id': {
                        'name': 'metric_name',
                    }
                }
            }
        """
        async with self.pg_pool.acquire() as conn:
            # Get preset metrics and user-enabled metrics
            rows = await conn.fetch("""
                -- Get preset metrics (available to all users)
                SELECT DISTINCT 
                    cmd.id, cmd.name, cmd.prompt, cmd.model, cmd.refresh_interval_hours,
                    'system' as user_id  -- Use 'system' for preset metrics
                FROM chat_metric_definitions cmd
                WHERE cmd.is_preset = true
                
                UNION ALL
                
                -- Get user-specific enabled metrics
                SELECT DISTINCT 
                    cmd.id, cmd.name, cmd.prompt, cmd.model, cmd.refresh_interval_hours,
                    um.user_id
                FROM chat_metric_definitions cmd
                INNER JOIN user_metric um ON cmd.id = um.metric_definition_id
                WHERE um.is_enabled = true
                
                ORDER BY user_id, id
            """)
            
            # Reorganize metrics by user_id
            self.metric_definitions = {}
            for row in rows:
                user_id = row['user_id']
                metric_id = row['id']
                
                if user_id not in self.metric_definitions:
                    self.metric_definitions[user_id] = {}
                    
                self.metric_definitions[user_id][metric_id] = {
                    'id': metric_id,
                    'name': row['name'],
                    'prompt': row['prompt'],
                    'model': row['model'],
                    'refresh_interval_hours': row['refresh_interval_hours']
                }
            
            logger.info(f"Loaded metrics for {len(self.metric_definitions)} users")

    async def process(self):
        """Find chats that need metric updates and queue them for processing"""
        async with self.pg_pool.acquire() as conn:
            # Find chats that need metric updates with user associations
            query = """
                WITH user_chats AS (
                    -- Get all enabled chats for each user through the association chain
                    SELECT DISTINCT 
                        u.id as user_id,
                        cm.id, cm.chat_id, cm.name, cm.username, cm.about, 
                        cm.participants_count, cm.admins
                    FROM users u
                    INNER JOIN user_account ua ON u.id = ua.user_id
                    INNER JOIN accounts a ON ua.account_id = a.id
                    INNER JOIN account_chat ac ON a.tg_id = ac.account_id
                    INNER JOIN chat_metadata cm ON ac.chat_id = cm.chat_id
                    WHERE ac.status = 'watching'
                )
                SELECT 
                    uc.*,
                    CASE 
                        WHEN cmv.id IS NULL THEN true  -- No metrics yet
                        WHEN cmv.next_refresh_at <= CURRENT_TIMESTAMP THEN true  -- Need refresh
                        ELSE false
                    END as needs_refresh
                FROM user_chats uc
                LEFT JOIN chat_metric_values cmv ON uc.chat_id = cmv.chat_id
                WHERE uc.chat_id != ALL($1)  -- Not currently processing
                AND (
                    cmv.id IS NULL  -- No metrics yet
                    OR cmv.next_refresh_at <= CURRENT_TIMESTAMP  -- Need refresh
                )
            """

            if self.is_testing:
                query = f"""
                    SELECT * FROM ({query}) sub
                    ORDER BY RANDOM() LIMIT $2
                """
                rows = await conn.fetch(query, list(self.processing_ids), self.test_limit)
            else:
                rows = await conn.fetch(query, list(self.processing_ids))
            
            if not rows:
                return

            # Organize chats by user_id
            user_chats = {}
            for row in rows:
                user_id = row['user_id']
                if user_id not in user_chats:
                    user_chats[user_id] = []
                
                if row['chat_id'] in self.processing_ids:
                    continue
                    
                self.processing_ids.add(row['chat_id'])
                chat_metadata = await self._to_chat_metadata(row, conn)
                user_chats[user_id].append(chat_metadata)

            # Queue chats for processing
            logger.info(f"Enqueueing chats for {len(user_chats)} users")
            for user_id, chats in user_chats.items():
                logger.info(f"User {user_id}: enqueueing {len(chats)} chats")
                for chat_metadata in chats:
                    await self.queue.put((user_id, chat_metadata))

    async def process_chat_metrics(self):
        """Worker that processes metrics for each chat"""
        while self.running:
            try:
                user_id, chat_metadata = await self.queue.get()
                logger.info(f"Processing metrics for user {user_id}, chat: {chat_metadata.name}")
                
                try:
                    async with self.pg_pool.acquire() as conn:
                        # Get context data
                        context = await self._gather_context(chat_metadata, conn)
                        
                        # Get metrics for this user
                        user_metrics = self.metric_definitions.get(user_id, {})
                        system_metrics = self.metric_definitions.get('system', {})
                        all_metrics = {**system_metrics, **user_metrics}  # User metrics override system metrics
                        
                        # Process each metric
                        for metric_id, metric_def in all_metrics.items():
                            try:
                                # Calculate metric
                                result = await self._calculate_metric(
                                    context, 
                                    metric_def['prompt'],
                                    metric_def['model']
                                )
                                
                                if result:
                                    # Store metric value
                                    await self._store_metric_value(
                                        conn,
                                        chat_metadata.chat_id,
                                        metric_id,
                                        result['value'],
                                        result['confidence'],
                                        result['reason'],
                                        metric_def['refresh_interval_hours']
                                    )
                            except Exception as e:
                                logger.error(f"Error processing metric {metric_def['name']}: {e}")
                                
                except Exception as e:
                    logger.error(f"Error processing chat {chat_metadata.chat_id}: {e}")
                finally:
                    self.processing_ids.remove(chat_metadata.chat_id)
                    self.queue.task_done()
                    
            except Exception as e:
                logger.error(f"Worker error: {e}")
                await asyncio.sleep(1)

    async def _calculate_metric(
        self, context: str, prompt: str, model: str
    ) -> Optional[Dict]:
        """Calculate a single metric value using AI"""
        try:
            # Add clear instructions about expected response format
            system_prompt = prompt.strip()
            user_prompt = f"""
Please analyze this Telegram group based on the provided context and guidelines:

{context}

Provide your analysis in the specified JSON format with value, confidence, and reason fields.
"""
            
            response = await self.agent_client.chat_completion(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.1,
                response_format={"type": "json_object"}
            )
            
            result = parse_ai_response(response)
            if not result:
                logger.warning("Failed to parse AI response")
                return None
                
            # Validate required fields
            if not all(k in result for k in ["value", "confidence", "reason"]):
                logger.warning(f"Missing required fields in result: {result}")
                return None
                
            # Ensure value is not None/empty
            if not result["value"]:
                logger.warning(f"Empty value in result: {result}")
                return None
                
            # Ensure confidence is a float between 0-100
            try:
                confidence = float(result["confidence"])
                if not (0 <= confidence <= 100):
                    raise ValueError("Confidence must be between 0 and 100")
            except (TypeError, ValueError) as e:
                logger.warning(f"Invalid confidence value: {e}")
                return None
                
            return {
                "value": str(result["value"]),  # Ensure value is string
                "confidence": confidence,
                "reason": str(result.get("reason", ""))  # Ensure reason is string
            }
            
        except Exception as e:
            logger.error(f"Error calculating metric: {e}")
            return None

    async def _store_metric_value(
        self,
        conn: asyncpg.Connection,
        chat_id: str,
        metric_id: int,
        value: str,
        confidence: float,
        reason: str,
        refresh_interval_hours: int
    ):
        """Store a metric value in the database"""
        
        await conn.execute("""
            INSERT INTO chat_metric_values (
                chat_id, metric_definition_id, value, confidence, reason,
                last_refresh_at, next_refresh_at
            ) VALUES ($1, $2, $3, $4, $5, CURRENT_TIMESTAMP, 
                     CURRENT_TIMESTAMP + INTERVAL '1 hour' * $6)
            ON CONFLICT (chat_id, metric_definition_id) DO UPDATE
            SET value = EXCLUDED.value,
                confidence = EXCLUDED.confidence,
                reason = EXCLUDED.reason,
                last_refresh_at = CURRENT_TIMESTAMP,
                next_refresh_at = CURRENT_TIMESTAMP + INTERVAL '1 hour' * $6
        """, chat_id, metric_id, value, confidence, reason, refresh_interval_hours)

    async def _gather_context(
        self, chat_metadata: ChatMetadata, conn: asyncpg.Connection
    ) -> str:
        """Gather context data for metric calculation"""
        # Get recent messages
        messages = await self._get_latest_messages(chat_metadata.chat_id, conn)
        
        # Build context
        context_parts = [
            f"Chat Name: {chat_metadata.name}",
            f"Description: {chat_metadata.about or 'No description'}",
            f"Participants: {chat_metadata.participants_count}",
            "\nRecent Messages:",
        ]
        
        for msg in messages:
            context_parts.append(gen_message_content(msg))
            
        return "\n".join(context_parts)

    async def _get_latest_messages(
        self, chat_id: str, conn: asyncpg.Connection, limit: int = 50
    ) -> List[ChatMessage]:
        """Get recent messages for a chat"""
        rows = await conn.fetch("""
            SELECT chat_id, message_id, reply_to, topic_id,
                   sender_id, message_text, buttons, message_timestamp
            FROM chat_messages 
            WHERE chat_id = $1
            ORDER BY message_timestamp DESC
            LIMIT $2
        """, chat_id, limit)
        
        messages = [db_row_to_chat_message(row) for row in rows]
        messages.reverse()
        return messages

    async def _to_chat_metadata(self, row: dict, conn) -> ChatMetadata:
        """Convert database row to ChatMetadata object"""
        
        admins = json.loads(row["admins"] or "[]")

        return ChatMetadata(
            chat_id=row['chat_id'],
            name=row['name'],
            username=row['username'],
            about=row['about'],
            participants_count=row['participants_count'],
            admins=admins
        )
