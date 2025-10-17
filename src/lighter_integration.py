#!/usr/bin/env python3
"""
Lighter Exchange Integration
Based on: https://github.com/your-quantguy/perp-dex-tools
"""

import os
import time
import asyncio
import logging
from decimal import Decimal
from typing import Dict, Optional

from lighter import SignerClient

logger = logging.getLogger(__name__)


class LighterClient:
    """Lighter Exchange Client"""

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
        self.market_info = {}  # Cache market information

    async def initialize(self):
        """Initialize the Lighter SignerClient"""
        if self.client is None:
            try:
                self.client = SignerClient(
                    url=self.base_url,
                    private_key=self.private_key,
                    account_index=self.account_index,
                    api_key_index=self.api_key_index,
                )

                # Validate client
                err = self.client.check_client()
                if err is not None:
                    raise Exception(f"Lighter client check failed: {err}")

                logger.info("Lighter client initialized successfully")
            except Exception as e:
                logger.error(f"Failed to initialize Lighter client: {e}")
                raise

    async def get_market_info(self, market_id: str) -> Dict:
        """
        Get market information and cache it

        Args:
            market_id: Market identifier (e.g., "BTC_USDC", "SOL_USDC")

        Returns:
            Market info with decimals
        """
        if market_id not in self.market_info:
            if self.client is None:
                await self.initialize()

            # Get market data from Lighter
            market = await self.client.get_market(market_id)
            self.market_info[market_id] = {
                "size_decimals": market.supported_size_decimals,
                "price_decimals": market.supported_price_decimals,
                "base_multiplier": 10 ** market.supported_size_decimals,
                "price_multiplier": 10 ** market.supported_price_decimals,
            }

        return self.market_info[market_id]

    async def get_position(self, market_id: str) -> float:
        """
        Get current position for a market

        Args:
            market_id: Market identifier

        Returns:
            Position size (negative for short, positive for long)
        """
        if self.client is None:
            await self.initialize()

        try:
            positions = await self.client.get_account_positions()

            for position in positions:
                if position.market_id == market_id:
                    return float(position.position)

            return 0.0

        except Exception as e:
            logger.error(f"Failed to get position for {market_id}: {e}")
            raise

    async def get_price(self, market_id: str) -> float:
        """
        Get current market price (mid price)

        Args:
            market_id: Market identifier

        Returns:
            Current mid price
        """
        if self.client is None:
            await self.initialize()

        try:
            # Get order book
            orderbook = await self.client.get_orderbook(market_id)

            if orderbook.bids and orderbook.asks:
                best_bid = float(orderbook.bids[0].price)
                best_ask = float(orderbook.asks[0].price)
                return (best_bid + best_ask) / 2

            return 0.0

        except Exception as e:
            logger.error(f"Failed to get price for {market_id}: {e}")
            raise

    async def place_limit_order(
        self,
        market_id: str,
        side: str,
        size: float,
        price: float,
        reduce_only: bool = False
    ) -> str:
        """
        Place a limit order

        Args:
            market_id: Market identifier
            side: "buy" or "sell"
            size: Order size
            price: Limit price
            reduce_only: Whether this is a reduce-only order

        Returns:
            Order ID
        """
        if self.client is None:
            await self.initialize()

        # Get market info for decimal conversion
        market_info = await self.get_market_info(market_id)

        # Convert to Lighter's integer format
        is_ask = side.lower() == "sell"
        base_amount = int(size * market_info["base_multiplier"])
        price_int = int(price * market_info["price_multiplier"])

        # Generate client order ID
        client_order_index = int(time.time() * 1000) % 1000000

        try:
            order_params = {
                'market_index': market_id,
                'client_order_index': client_order_index,
                'base_amount': base_amount,
                'price': price_int,
                'is_ask': is_ask,
                'order_type': self.client.ORDER_TYPE_LIMIT,
                'time_in_force': self.client.ORDER_TIME_IN_FORCE_GOOD_TILL_TIME,
                'reduce_only': reduce_only,
                'trigger_price': 0,
            }

            order_result, tx_hash, error = await self.client.create_order(**order_params)

            if error:
                raise Exception(f"Order creation failed: {error}")

            logger.info(f"Limit order placed: {side} {size} @ {price}, tx: {tx_hash}")
            return str(order_result.order_id) if order_result else tx_hash

        except Exception as e:
            logger.error(f"Failed to place limit order: {e}")
            raise

    async def place_market_order(
        self,
        market_id: str,
        side: str,
        size: float
    ) -> str:
        """
        Place a market order (using IOC limit order at extreme price)

        Args:
            market_id: Market identifier
            side: "buy" or "sell"
            size: Order size

        Returns:
            Order ID
        """
        # Get current market price
        current_price = await self.get_price(market_id)

        # Use extreme price to ensure immediate execution
        if side.lower() == "buy":
            price = current_price * 1.05  # 5% above market
        else:
            price = current_price * 0.95  # 5% below market

        # Place IOC limit order
        return await self.place_limit_order(
            market_id=market_id,
            side=side,
            size=size,
            price=price,
            reduce_only=False
        )

    async def cancel_order(self, market_id: str, order_id: str) -> bool:
        """
        Cancel an order

        Args:
            market_id: Market identifier
            order_id: Order ID to cancel

        Returns:
            True if successful
        """
        if self.client is None:
            await self.initialize()

        try:
            cancel_result, tx_hash, error = await self.client.cancel_order(
                market_index=market_id,
                order_id=int(order_id)
            )

            if error:
                raise Exception(f"Order cancellation failed: {error}")

            logger.info(f"Order canceled: {order_id}, tx: {tx_hash}")
            return True

        except Exception as e:
            logger.error(f"Failed to cancel order {order_id}: {e}")
            return False

    async def get_order_status(self, market_id: str, order_id: str) -> Dict:
        """
        Get order status

        Args:
            market_id: Market identifier
            order_id: Order ID

        Returns:
            Order status dict
        """
        if self.client is None:
            await self.initialize()

        try:
            order = await self.client.get_order(
                market_index=market_id,
                order_id=int(order_id)
            )

            if order:
                return {
                    "status": "open" if order.is_active else "filled",
                    "filled_size": float(order.filled_size or 0),
                    "remaining_size": float(order.remaining_size or 0),
                }

            return {
                "status": "not_found",
                "filled_size": 0.0,
                "remaining_size": 0.0,
            }

        except Exception as e:
            logger.error(f"Failed to get order status for {order_id}: {e}")
            raise
