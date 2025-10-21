#!/usr/bin/env python3
"""
Lighter Exchange Client - Core client initialization
"""

import logging
from typing import Optional

from lighter import SignerClient, ApiClient, Configuration, AccountApi

logger = logging.getLogger(__name__)


class LighterBaseClient:
    """Base client for Lighter Exchange with initialization logic"""

    def __init__(
        self,
        private_key: str,
        account_index: int = 0,
        api_key_index: int = 0,
        base_url: str = "https://mainnet.zklighter.elliot.ai"
    ):
        """
        Initialize Lighter client

        Args:
            private_key: API private key
            account_index: Account index (default: 0)
            api_key_index: API key index (default: 0)
            base_url: Lighter API base URL
        """
        self.private_key = private_key
        self.account_index = account_index
        self.api_key_index = api_key_index
        self.base_url = base_url
        self.client: Optional[SignerClient] = None
        self.api_client: Optional[ApiClient] = None
        self.account_api: Optional[AccountApi] = None

    async def initialize(self):
        """Initialize the Lighter SignerClient and AccountApi"""
        if self.client is None:
            try:
                logger.info(f"Initializing Lighter client (account_index={self.account_index})")

                # Initialize SignerClient for trading operations
                self.client = SignerClient(
                    url=self.base_url,
                    private_key=self.private_key,
                    account_index=self.account_index,
                    api_key_index=self.api_key_index,
                )

                # Initialize ApiClient and AccountApi for account data queries
                config = Configuration(host=self.base_url)
                self.api_client = ApiClient(configuration=config)
                self.account_api = AccountApi(self.api_client)

                # Validate API key
                err = self.client.check_client()
                if err is not None:
                    logger.error(f"API key validation failed: {err}")
                    raise Exception(f"Invalid API key: {err}")

                logger.info(f"Lighter client initialized successfully")

            except Exception as e:
                logger.error(f"Failed to initialize Lighter client: {e}")
                raise
