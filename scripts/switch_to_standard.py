#!/usr/bin/env python3
"""
Switch Lighter account from Premium to Standard tier

Requirements:
- No open positions
- No open orders
- At least 24 hours since last tier change
"""

import asyncio
import logging
import sys
import os
import json
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# Load .env file
from dotenv import load_dotenv
env_path = Path(__file__).parent.parent / ".env"
if env_path.exists():
    load_dotenv(env_path)
    logger_setup = logging.getLogger(__name__)
    logger_setup.info(f"Loaded environment from {env_path}")

import lighter
import requests

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load config
config_path = Path(__file__).parent.parent / "config.json"
if config_path.exists():
    with open(config_path, 'r') as f:
        config = json.load(f)
else:
    config = {}

# Get credentials from environment or config
BASE_URL = os.getenv("EXCHANGE_BASE_URL", config.get("exchange", {}).get("base_url", "https://mainnet.zklighter.elliot.ai"))
API_KEY_PRIVATE_KEY = os.getenv("EXCHANGE_PRIVATE_KEY", config.get("exchange", {}).get("private_key", ""))
ACCOUNT_INDEX = int(os.getenv("EXCHANGE_ACCOUNT_INDEX", config.get("exchange", {}).get("account_index", 0)))
API_KEY_INDEX = int(os.getenv("EXCHANGE_API_KEY_INDEX", config.get("exchange", {}).get("api_key_index", 0)))


async def check_preconditions(client):
    """Check if we can switch tiers"""
    logger.info("Checking preconditions...")

    # Initialize API client
    config = lighter.Configuration(host=BASE_URL)
    api_client = lighter.ApiClient(configuration=config)
    account_api = lighter.AccountApi(api_client)

    # Get account data
    response = await account_api.account(by="index", value=str(ACCOUNT_INDEX))

    if response and hasattr(response, 'accounts') and len(response.accounts) > 0:
        account = response.accounts[0]

        # Check positions
        if hasattr(account, 'positions') and account.positions:
            active_positions = [p for p in account.positions if float(p.position) != 0]
            if active_positions:
                logger.error(f"❌ Cannot switch: You have {len(active_positions)} open positions")
                logger.error("Please close all positions first")
                return False

        logger.info("✅ No open positions")

    # Check orders
    order_api = lighter.OrderApi(api_client)
    active_orders = await order_api.account_active_orders(by="index", value=str(ACCOUNT_INDEX))

    if active_orders and hasattr(active_orders, 'orders') and active_orders.orders:
        logger.error(f"❌ Cannot switch: You have {len(active_orders.orders)} open orders")
        logger.error("Please cancel all orders first")
        return False

    logger.info("✅ No open orders")

    await api_client.close()
    return True


async def switch_to_standard():
    """Switch account to Standard tier"""

    logger.info("=" * 60)
    logger.info("Switching Lighter Account to Standard Tier")
    logger.info("=" * 60)

    if not API_KEY_PRIVATE_KEY:
        logger.error("❌ API_KEY_PRIVATE_KEY not found in config or environment")
        return False

    # Initialize client
    client = lighter.SignerClient(
        url=BASE_URL,
        private_key=API_KEY_PRIVATE_KEY,
        account_index=ACCOUNT_INDEX,
        api_key_index=API_KEY_INDEX,
    )

    # Check client
    err = client.check_client()
    if err is not None:
        logger.error(f"❌ Client check failed: {err}")
        return False

    logger.info("✅ Client validated")

    # Check preconditions
    if not await check_preconditions(client):
        return False

    # Create auth token
    logger.info("Creating auth token...")
    auth, err = client.create_auth_token_with_expiry(
        lighter.SignerClient.DEFAULT_10_MIN_AUTH_EXPIRY
    )

    if err is not None:
        logger.error(f"❌ Failed to create auth token: {err}")
        return False

    # Switch tier
    logger.info(f"Switching account {ACCOUNT_INDEX} to Standard tier...")

    response = requests.post(
        f"{BASE_URL}/api/v1/changeAccountTier",
        data={"account_index": ACCOUNT_INDEX, "new_tier": "standard"},
        headers={"Authorization": auth},
    )

    if response.status_code != 200:
        logger.error(f"❌ Failed to switch tier: {response.text}")

        # Check if it's a 24-hour restriction
        if "24 hours" in response.text.lower():
            logger.error("You need to wait 24 hours since your last tier change")

        return False

    result = response.json()
    logger.info("=" * 60)
    logger.info("✅ Successfully switched to Standard tier!")
    logger.info("=" * 60)
    logger.info(f"Response: {json.dumps(result, indent=2)}")
    logger.info("")
    logger.info("Standard Account Benefits:")
    logger.info("  • 0% Maker / 0% Taker fees")
    logger.info("  • No minimum order size restrictions")
    logger.info("  • 200ms maker/cancel latency")
    logger.info("  • 300ms taker latency")
    logger.info("")
    logger.info("You can now restart your hedge bot!")

    await client.close()
    return True


async def main():
    try:
        success = await switch_to_standard()
        sys.exit(0 if success else 1)
    except Exception as e:
        logger.error(f"❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
