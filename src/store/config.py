import os
from pathlib import Path
from dotenv import load_dotenv

env_path = Path(__file__).parent.parent.parent / ".env"
load_dotenv(env_path)

ACCOUNT_SIZE = float(os.getenv("ACCOUNT_SIZE", "100"))
WEBULL_ACCOUNT_ID = os.getenv("WEBULL_ACCOUNT_ID", "")
WEBULL_ACCESS_TOKEN = os.getenv("WEBULL_ACCESS_TOKEN", "")
WALLET_ADDRESSES = [
    a.strip() for a in os.getenv("WALLET_ADDRESSES", "").split(",") if a.strip()
]
SOLANA_RPC = os.getenv("SOLANA_RPC", "https://api.mainnet-beta.solana.com")
BIRDEYE_API_KEY = os.getenv("BIRDEYE_API_KEY", "")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")
SCRAPE_URLS = [u.strip() for u in os.getenv("SCRAPE_URLS", "").split(",") if u.strip()]

DB_PATH = Path(__file__).parent.parent.parent / "data" / "scanner.db"

TOP_TRADERS_MIN_CALLS = int(os.getenv("TOP_TRADERS_MIN_CALLS", "10"))
TOP_TRADERS_MIN_PNL = float(os.getenv("TOP_TRADERS_MIN_PNL", "1000"))
TOP_TRADERS_MAX_CAP = float(os.getenv("TOP_TRADERS_MAX_CAP", "5000"))
