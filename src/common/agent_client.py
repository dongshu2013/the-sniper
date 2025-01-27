import logging

from openai import AsyncOpenAI

from .config import DEEPSEEK_API_KEY, DEEPSEEK_API_URL, DEEPSEEK_MODEL_NAME

logger = logging.getLogger(__name__)


class AgentClient:
    def __init__(self):
        self.client = AsyncOpenAI(
            api_key=DEEPSEEK_API_KEY,
            base_url=DEEPSEEK_API_URL,
        )
        self.model = DEEPSEEK_MODEL_NAME
        logger.info(f"Using model: {self.model}")

    async def chat_completion(
        self, messages, temperature=0.1, response_format=None
    ) -> str | None:
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            response_format=response_format,
        )
        if response.choices:
            return response.choices[0].message.content
        else:
            logger.error(f"No response from {self.model}: {response}")
            return None
