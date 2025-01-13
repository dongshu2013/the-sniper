import os
from dotenv import load_dotenv

load_dotenv()

# Database configs
POSTGRES_CONFIG = {
    'host': os.getenv('POSTGRES_HOST', '127.0.0.1'),
    'port': int(os.getenv('POSTGRES_PORT', 5432)),
    'user': os.getenv('POSTGRES_USER', 'kevin'),
    'password': os.getenv('POSTGRES_PASSWORD', ''),
    'database': os.getenv('POSTGRES_DB', 'gmgn_memes')
}

# Browser configs
PLAYWRIGHT_CONFIG = {
    "launch_options": {
        "headless": True,
        "proxy": {
            "server": os.getenv('PROXY_SERVER', 'http://127.0.0.1:7890')
        }
    },
    "context_options": {
        "viewport": {"width": 1280, "height": 800},
        "extra_http_headers": {
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
    }
}

# Scraping configs
DOWNLOAD_DELAY = 15  # seconds
RETRY_TIMES = 3
RETRY_HTTP_CODES = [403, 429] 