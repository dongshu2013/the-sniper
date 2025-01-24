import argparse
import asyncio
import json
import logging

import phonenumbers
from redis.asyncio import Redis

from src.common.config import REDIS_URL
from src.processors.new_account import (
    NEW_ACCOUNT_REQUEST_KEY,
    phone_code_key,
    phone_status_key,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

redis_client = Redis.from_url(REDIS_URL)


async def create_new_account(phone: str):
    try:
        libphonenumber = phonenumbers.parse(phone)
        phone_number = phonenumbers.format_number(
            libphonenumber, phonenumbers.PhoneNumberFormat.E164
        )
        await redis_client.lpush(
            NEW_ACCOUNT_REQUEST_KEY, json.dumps({"phone": phone_number})
        )
        code = input("Please input the code to continue: ")
        await redis_client.set(phone_code_key(phone_number), code)
        while True:
            status = await redis_client.get(phone_status_key(phone_number))
            if status is not None:
                break
            await asyncio.sleep(1)

        if status == "success":
            logger.info(f"Successfully created account for {phone_number}")
        else:
            logger.error(
                f"Failed to create account for {phone_number} with status {status}"
            )

    except Exception as e:
        logger.error(f"Failed to create account: {e}")
        raise


def main():
    parser = argparse.ArgumentParser(description="Create a new Telegram account entry")
    parser.add_argument(
        "--phone", required=True, help="Phone number in international format"
    )
    args = parser.parse_args()
    asyncio.run(create_new_account(args.phone))


if __name__ == "__main__":
    main()
