from openai import AsyncOpenAI

from .config import MODEL_NAME, OPENROUTER_API_KEY, OPENROUTER_API_URL


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

    async def chat_completion(self, messages):
        response = await self.client.chat.completions.create(
            model=self.model, messages=messages
        )
        return response.model_dump()
