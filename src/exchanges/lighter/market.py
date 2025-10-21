#!/usr/bin/env python3
"""
Lighter Exchange - Market information and price queries
"""

import logging
import traceback
from typing import Dict

from .client import LighterBaseClient
from .types import REQUIRED_MARKETS, MarketInfo
from .utils import convert_1000x_size

logger = logging.getLogger(__name__)


class LighterMarketManager(LighterBaseClient):
    """Manages market information and price queries for Lighter exchange"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.market_info: Dict[int, MarketInfo] = {}  # Cache market information
        self.symbol_to_market_id: Dict[str, int] = {}  # Map symbol (SOL) to market_id (int)

    async def _load_markets(self):
        """Load only the 4 required markets (BTC, ETH, SOL, 1000BONK)"""
        if self.symbol_to_market_id:
            return  # Already loaded

        if self.client is None:
            await self.initialize()

        try:
            # Get all available markets (returns OrderBooks object)
            # See: https://github.com/elliottech/lighter-python/blob/main/lighter/models/order_books.py
            order_books_response = await self.client.order_api.order_books()

            # OrderBooks has .order_books field which is List[OrderBook]
            markets = order_books_response.order_books

            logger.info(f"Filtering {len(markets)} markets for required symbols: {REQUIRED_MARKETS}")

            for market in markets:
                symbol = market.symbol

                # Skip markets we don't need
                if symbol not in REQUIRED_MARKETS:
                    continue

                # OrderBook fields: symbol, market_id, supported_size_decimals, supported_price_decimals
                # See: https://github.com/elliottech/lighter-python/blob/main/lighter/models/order_book.py
                market_id = market.market_id
                size_decimals = market.supported_size_decimals
                price_decimals = market.supported_price_decimals

                logger.debug(f"Market: {symbol} (ID={market_id}, size_dec={size_decimals}, price_dec={price_decimals})")

                # Only load active markets
                if market.status == 'active':
                    self.symbol_to_market_id[symbol] = market_id
                    self.market_info[market_id] = {
                        "symbol": symbol,
                        "size_decimals": size_decimals,
                        "price_decimals": price_decimals,
                        "base_multiplier": 10 ** size_decimals,
                        "price_multiplier": 10 ** price_decimals,
                    }
                else:
                    logger.debug(f"Skipping {symbol} (status={market.status})")

            logger.info(f"Loaded {len(self.symbol_to_market_id)} required markets")
            logger.info(f"Available markets: {sorted(self.symbol_to_market_id.keys())}")

        except Exception as e:
            logger.error(f"Failed to load markets: {e}")
            logger.error(traceback.format_exc())
            raise

    async def get_market_id(self, symbol: str) -> int:
        """
        Get numeric market ID from symbol

        Args:
            symbol: Market symbol (e.g., "SOL", "BTC")

        Returns:
            Numeric market ID
        """
        if not self.symbol_to_market_id:
            await self._load_markets()

        if symbol not in self.symbol_to_market_id:
            raise ValueError(f"Market {symbol} not found on Lighter")

        return self.symbol_to_market_id[symbol]

    async def get_market_info(self, symbol: str) -> MarketInfo:
        """
        Get market information

        Args:
            symbol: Market symbol (e.g., "BTC", "SOL")

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
            symbol: Market symbol (e.g., "SOL", "1000BONK")

        Returns:
            Position size (negative for short, positive for long, in actual token amount)
        """
        if self.account_api is None:
            await self.initialize()

        try:
            # Get numeric market ID
            market_id = await self.get_market_id(symbol)

            # Get account data using AccountApi
            response = await self.account_api.account(
                by="index",
                value=str(self.account_index)
            )

            # Response structure: {accounts: [DetailedAccount{..., positions: [...]}]}
            if response and hasattr(response, 'accounts') and len(response.accounts) > 0:
                account = response.accounts[0]

                if hasattr(account, 'positions'):
                    for position in account.positions:
                        if position.market_id == market_id:
                            # Position is already in decimal format (e.g., "1.000")
                            pos = float(position.position)

                            # Apply sign: -1 for short, 1 for long
                            if hasattr(position, 'sign'):
                                pos = pos * position.sign

                            # Convert for 1000X markets (e.g., 1000BONK)
                            pos = convert_1000x_size(symbol, pos, to_lighter=False)

                            return pos

            return 0.0

        except Exception as e:
            logger.error(f"Failed to get position for {symbol}: {e}")
            logger.error(traceback.format_exc())
            raise

    async def get_price(self, symbol: str) -> float:
        """
        Get current market price (mid price)

        Args:
            symbol: Market symbol (e.g., "SOL", "1000BONK")

        Returns:
            Current mid price (per single token, adjusted for 1000X markets)
        """
        if self.client is None:
            await self.initialize()

        try:
            # Get numeric market ID
            market_id = await self.get_market_id(symbol)

            # Get order book using order_api
            orderbook = await self.client.order_api.order_book_orders(
                market_id=market_id,
                limit=1  # Only need best bid/ask
            )

            price = 0.0

            if orderbook and hasattr(orderbook, 'bids') and hasattr(orderbook, 'asks'):
                if orderbook.bids and orderbook.asks:
                    # bids[0] and asks[0] are SimpleOrder objects with .price attribute
                    # Price is already in correct format (string like "3726.21"), no need to divide
                    best_bid = float(orderbook.bids[0].price)
                    best_ask = float(orderbook.asks[0].price)
                    price = (best_bid + best_ask) / 2

            # Fallback: try to get from recent trades
            if price == 0.0:
                trades = await self.client.order_api.recent_trades(
                    market_id=market_id,
                    limit=1
                )

                if trades and len(trades) > 0:
                    # trades[0] is likely also an object with .price attribute
                    trade_price = getattr(trades[0], 'price', None)
                    if trade_price:
                        price = float(trade_price)

            if price == 0.0:
                logger.warning(f"No price data available for {symbol}")
                return 0.0

            # For 1000X markets (e.g., 1000BONK), the price is for 1000 tokens
            # We need to divide by 1000 to get the price per single token
            if symbol.startswith("1000"):
                price = price / 1000

            return price

        except Exception as e:
            logger.error(f"Failed to get price for {symbol}: {e}")
            raise
