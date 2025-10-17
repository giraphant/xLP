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
        self.symbol_to_market_id = {}  # Map symbol (SOL_USDC) to market_id (int)

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

                # Skip check_client() due to SDK bug with sub-accounts
                # The SDK has issues validating sub-accounts and non-zero api_key_index
                # Instead, we'll verify by making a simple API call
                logger.info(f"Lighter client initialized (account_index={self.account_index}, api_key_index={self.api_key_index})")
                logger.warning("Skipping check_client() due to known SDK issue with sub-accounts")

            except Exception as e:
                logger.error(f"Failed to initialize Lighter client: {e}")
                raise

    async def _load_markets(self):
        """Load all markets and build symbol-to-ID mapping"""
        if self.symbol_to_market_id:
            return  # Already loaded

        if self.client is None:
            await self.initialize()

        try:
            # Get all available markets
            markets = await self.client.order_api.order_books()

            logger.debug(f"Received {len(markets) if markets else 0} markets from API")

            if markets:
                # Log first market to see structure
                if len(markets) > 0:
                    first_market = markets[0]
                    logger.debug(f"First market object: {first_market}")
                    logger.debug(f"First market attributes: {dir(first_market)}")

                for market in markets:
                    # Try different possible field names
                    symbol = None
                    for attr in ['symbol', 'name', 'market_symbol', 'pair', 'market_name']:
                        if hasattr(market, attr):
                            symbol = getattr(market, attr)
                            if symbol:
                                break

                    # Try to get market_id
                    market_id = getattr(market, 'market_id', getattr(market, 'id', None))

                    logger.debug(f"Market: symbol={symbol}, id={market_id}")

                    if symbol and market_id is not None:
                        self.symbol_to_market_id[symbol] = market_id
                        self.market_info[market_id] = {
                            "symbol": symbol,
                            "size_decimals": getattr(market, 'size_decimals', 9),
                            "price_decimals": getattr(market, 'price_decimals', 6),
                            "base_multiplier": 10 ** getattr(market, 'size_decimals', 9),
                            "price_multiplier": 10 ** getattr(market, 'price_decimals', 6),
                        }

            logger.info(f"Loaded {len(self.symbol_to_market_id)} markets from Lighter")
            if self.symbol_to_market_id:
                logger.info(f"Available markets: {list(self.symbol_to_market_id.keys())}")

        except Exception as e:
            logger.error(f"Failed to load markets: {e}")
            import traceback
            logger.error(traceback.format_exc())
            raise

    async def get_market_id(self, symbol: str) -> int:
        """
        Get numeric market ID from symbol

        Args:
            symbol: Market symbol (e.g., "SOL_USDC", "BTC_USDC")

        Returns:
            Numeric market ID
        """
        if not self.symbol_to_market_id:
            await self._load_markets()

        if symbol not in self.symbol_to_market_id:
            raise ValueError(f"Market {symbol} not found on Lighter")

        return self.symbol_to_market_id[symbol]

    async def get_market_info(self, symbol: str) -> Dict:
        """
        Get market information

        Args:
            symbol: Market symbol (e.g., "BTC_USDC", "SOL_USDC")

        Returns:
            Market info with decimals
        """
        market_id = await self.get_market_id(symbol)

        if market_id not in self.market_info:
            await self._load_markets()

        return self.market_info[market_id]

    async def get_position(self, symbol: str) -> float:
        """
        Get current position for a market

        Args:
            symbol: Market symbol (e.g., "SOL_USDC")

        Returns:
            Position size (negative for short, positive for long)
        """
        if self.client is None:
            await self.initialize()

        try:
            # Get numeric market ID
            market_id = await self.get_market_id(symbol)

            # Get account positions using account_api
            positions = await self.client.account_api.account_positions(
                auth_token=await self.client.create_auth_token()
            )

            if positions and hasattr(positions, 'positions'):
                for position in positions.positions:
                    if position.market_id == market_id:
                        # Position is in Lighter's integer format, need to convert
                        market_info = await self.get_market_info(symbol)
                        return float(position.position) / market_info["base_multiplier"]

            return 0.0

        except Exception as e:
            logger.error(f"Failed to get position for {symbol}: {e}")
            raise

    async def get_price(self, symbol: str) -> float:
        """
        Get current market price (mid price)

        Args:
            symbol: Market symbol (e.g., "SOL_USDC")

        Returns:
            Current mid price
        """
        if self.client is None:
            await self.initialize()

        try:
            # Get numeric market ID
            market_id = await self.get_market_id(symbol)
            market_info = await self.get_market_info(symbol)

            # Get order book using order_api
            orderbook = await self.client.order_api.order_book_orders(
                market_id=market_id,
                limit=1  # Only need best bid/ask
            )

            if orderbook and hasattr(orderbook, 'bids') and hasattr(orderbook, 'asks'):
                if orderbook.bids and orderbook.asks:
                    # Prices are in integer format, convert to float
                    best_bid = float(orderbook.bids[0]['price']) / market_info["price_multiplier"]
                    best_ask = float(orderbook.asks[0]['price']) / market_info["price_multiplier"]
                    return (best_bid + best_ask) / 2

            # Fallback: try to get from recent trades
            trades = await self.client.order_api.recent_trades(
                market_id=market_id,
                limit=1
            )

            if trades and len(trades) > 0:
                return float(trades[0]['price']) / market_info["price_multiplier"]

            logger.warning(f"No price data available for {symbol}")
            return 0.0

        except Exception as e:
            logger.error(f"Failed to get price for {symbol}: {e}")
            raise

    async def place_limit_order(
        self,
        symbol: str,
        side: str,
        size: float,
        price: float,
        reduce_only: bool = False
    ) -> str:
        """
        Place a limit order

        Args:
            symbol: Market symbol (e.g., "SOL_USDC")
            side: "buy" or "sell"
            size: Order size
            price: Limit price
            reduce_only: Whether this is a reduce-only order

        Returns:
            Order ID
        """
        if self.client is None:
            await self.initialize()

        # Get market ID and info
        market_id = await self.get_market_id(symbol)
        market_info = await self.get_market_info(symbol)

        # Convert to Lighter's integer format
        is_ask = side.lower() == "sell"
        base_amount = int(size * market_info["base_multiplier"])
        price_int = int(price * market_info["price_multiplier"])

        # Generate client order ID
        client_order_index = int(time.time() * 1000) % 1000000

        try:
            order_params = {
                'market_index': market_id,  # Now using numeric ID
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
        symbol: str,
        side: str,
        size: float
    ) -> str:
        """
        Place a market order (using IOC limit order at extreme price)

        Args:
            symbol: Market symbol (e.g., "SOL_USDC")
            side: "buy" or "sell"
            size: Order size

        Returns:
            Order ID
        """
        # Get current market price
        current_price = await self.get_price(symbol)

        # Use extreme price to ensure immediate execution
        if side.lower() == "buy":
            price = current_price * 1.05  # 5% above market
        else:
            price = current_price * 0.95  # 5% below market

        # Place IOC limit order
        return await self.place_limit_order(
            symbol=symbol,
            side=side,
            size=size,
            price=price,
            reduce_only=False
        )

    async def cancel_order(self, symbol: str, order_id: str) -> bool:
        """
        Cancel an order

        Args:
            symbol: Market symbol (e.g., "SOL_USDC")
            order_id: Order ID to cancel

        Returns:
            True if successful
        """
        if self.client is None:
            await self.initialize()

        try:
            market_id = await self.get_market_id(symbol)

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

    async def get_order_status(self, symbol: str, order_id: str) -> Dict:
        """
        Get order status

        Args:
            symbol: Market symbol (e.g., "SOL_USDC")
            order_id: Order ID

        Returns:
            Order status dict
        """
        if self.client is None:
            await self.initialize()

        try:
            market_id = await self.get_market_id(symbol)
            market_info = await self.get_market_info(symbol)

            # Get active orders for the account
            auth_token = await self.client.create_auth_token()
            active_orders = await self.client.order_api.account_active_orders(
                auth_token=auth_token,
                market_id=market_id
            )

            # Check if our order is in active orders
            if active_orders:
                for order in active_orders:
                    if str(order.order_id) == str(order_id):
                        return {
                            "status": "open",
                            "filled_size": float(order.filled_size or 0) / market_info["base_multiplier"],
                            "remaining_size": float(order.size - (order.filled_size or 0)) / market_info["base_multiplier"],
                        }

            # Not in active orders, check inactive orders (filled/canceled)
            inactive_orders = await self.client.order_api.account_inactive_orders(
                auth_token=auth_token,
                market_id=market_id,
                limit=20  # Check recent inactive orders
            )

            if inactive_orders:
                for order in inactive_orders:
                    if str(order.order_id) == str(order_id):
                        return {
                            "status": "filled" if order.is_filled else "canceled",
                            "filled_size": float(order.filled_size or 0) / market_info["base_multiplier"],
                            "remaining_size": 0.0,
                        }

            return {
                "status": "not_found",
                "filled_size": 0.0,
                "remaining_size": 0.0,
            }

        except Exception as e:
            logger.error(f"Failed to get order status for {order_id}: {e}")
            raise
