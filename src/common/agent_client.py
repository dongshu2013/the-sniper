import logging

from openai import AsyncOpenAI

from .config import MODEL_NAME, OPENROUTER_API_KEY, OPENROUTER_API_URL

logger = logging.getLogger(__name__)


class AgentClient:
    def __init__(self):
        self.client = AsyncOpenAI(
            api_key=OPENROUTER_API_KEY,
            base_url=OPENROUTER_API_URL,
            default_headers={
                "HTTP-Referer": "https://your-site.com",
                "X-Title": "the-sniper",
            },
        )
        self.model = MODEL_NAME
        logger.info(f"Using model: {self.model}")

    async def chat_completion(self, messages, temperature=0.1, response_format=None):
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            response_format=response_format,
        )
        return response.choices[0].message.content
