import json
import logging
import re

logger = logging.getLogger(__name__)


def parse_ai_response(response: str | None, fields: list[str] = None) -> dict:
    if not response:
        return {}

    try:
        # First try direct JSON parsing
        return json.loads(response)
    except json.JSONDecodeError:
        # If that fails, try to extract JSON from markdown
        if response.startswith("```json"):
            logger.info("Found JSON in markdown")
            # Remove markdown formatting
            cleaned_result = response.replace("```json\n", "").replace("\n```", "")
            try:
                return json.loads(cleaned_result)
            except json.JSONDecodeError:
                pass

        logger.info(f"Trying regex to extract JSON: {response}")
        # Last resort: try to extract using regex

        result = {}
        for field in fields or []:
            match = re.search(rf'{field}"?\s*:\s*"([^"]+)"', response)
            if match and match.group(1):
                result[field] = match.group(1)
            else:
                result[field] = None

        # exclude none fields
        result = {k: v for k, v in result.items() if v is not None}
        return result


def normalize_chat_id(chat_id: str | int) -> str:
    chat_id = str(chat_id)
    if chat_id.startswith("-100"):
        return chat_id[4:]
    elif chat_id.startswith("-"):
        return chat_id[1:]
    return chat_id
