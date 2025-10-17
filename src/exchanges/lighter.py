#!/usr/bin/env python3
"""
Lighter Exchange Integration
Based on: https://github.com/your-quantguy/perp-dex-tools
"""

import time
import logging
import traceback
from typing import Dict, Optional

from lighter import SignerClient, ApiClient, Configuration, AccountApi

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
        self.api_client: Optional[ApiClient] = None
        self.account_api: Optional[AccountApi] = None
        self.market_info = {}  # Cache market information
        self.symbol_to_market_id = {}  # Map symbol (SOL_USDC) to market_id (int)

    def _convert_1000x_size(self, symbol: str, size: float, to_lighter: bool) -> float:
        """
        Convert size for 1000X markets (e.g., 1000BONK)

        On Lighter: 1 unit of 1000BONK = 1000 actual BONK tokens

        Args:
            symbol: Market symbol
            size: Size to convert
            to_lighter: True to convert to Lighter format (divide by 1000),
                       False to convert from Lighter format (multiply by 1000)

        Returns:
            Converted size
        """
        if symbol.startswith("1000"):
            return size / 1000 if to_lighter else size * 1000
        return size

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

    async def _load_markets(self):
        """Load only the 4 required markets (BTC, ETH, SOL, 1000BONK)"""
        if self.symbol_to_market_id:
            return  # Already loaded

        if self.client is None:
            await self.initialize()

        # Only load markets we actually need for performance
        REQUIRED_MARKETS = {"BTC", "ETH", "SOL", "1000BONK"}

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
                            pos = self._convert_1000x_size(symbol, pos, to_lighter=False)

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
            symbol: Market symbol (e.g., "SOL", "1000BONK")
            side: "buy" or "sell"
            size: Order size (in actual token amount, will be converted for 1000X markets)
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

        # Save original size for USD calculation (before conversion)
        original_size = size

        # Convert size for 1000X markets (e.g., 1000BONK)
        size = self._convert_1000x_size(symbol, size, to_lighter=True)

        # Convert to Lighter's integer format
        is_ask = side.lower() == "sell"
        base_amount = int(size * market_info["base_multiplier"])
        price_int = int(price * market_info["price_multiplier"])

        # Log order details for debugging
        logger.info(f"📝 Limit Order calculation for {symbol}:")
        logger.info(f"  Size: {size:.8f} {symbol}")
        logger.info(f"  Base multiplier: {market_info['base_multiplier']} (decimals: {market_info['size_decimals']})")
        logger.info(f"  BaseAmount (integer): {base_amount}")
        logger.info(f"  Price: ${price:.2f}, Price int: {price_int}")

        # Calculate order value in USD using ORIGINAL size (before 1000X conversion)
        # Because price is per single token, not per 1000 tokens
        order_value_usd = original_size * price
        logger.info(f"  Order value: ${order_value_usd:.2f}")

        # Check minimum order size
        # BaseAmount must be >= 1 (API requirement)
        if base_amount < 1:
            raise ValueError(f"Order size too small: {size:.8f} {symbol} (BaseAmount={base_amount}, minimum is 1)")

        # Check L2 minimum order size (discovered through live testing)
        # L2 Sequencer rejects very small orders even if API accepts them
        #
        # Test results (SOL):
        # - BaseAmount=35 ($6.43): ❌ rejected
        # - BaseAmount=54 ($9.98): ✅ success
        # - Minimum appears to be ~$10 USD or BaseAmount ≥ 50
        #
        # Using conservative minimums based on ~$10 USD value:
        MIN_ORDER_VALUE_USD = 10.0

        if order_value_usd < MIN_ORDER_VALUE_USD:
            raise ValueError(
                f"Order too small for L2: ${order_value_usd:.2f} < ${MIN_ORDER_VALUE_USD:.2f} minimum. "
                f"Size {size:.8f} {symbol} (BaseAmount={base_amount}). "
                f"Increase CLOSE_RATIO or wait for larger offset to avoid rejected orders."
            )

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

            order_result, tx_response, error = await self.client.create_order(**order_params)

            if error:
                logger.error(f"Order creation failed: {error}")
                raise Exception(f"Order creation failed: {error}")

            # Log the actual API response
            logger.info(f"📡 API Response: code={tx_response.code}, message={tx_response.message}, tx_hash={tx_response.tx_hash}")

            # Check response code - need to understand what indicates success
            if tx_response.code != 200:
                logger.error(f"Order rejected by exchange: code={tx_response.code}, message={tx_response.message}")
                raise Exception(f"Order rejected: {tx_response.message or 'Unknown error'}")

            # Check for additional error information in response
            if tx_response.message and "error" in tx_response.message.lower():
                logger.warning(f"Potential error in response message: {tx_response.message}")

            # Log additional_properties if present (might contain important info)
            if hasattr(tx_response, 'additional_properties') and tx_response.additional_properties:
                logger.info(f"Additional response data: {tx_response.additional_properties}")

            # For cancellation, use the client_order_index we generated
            # This is the correct way according to official examples
            order_index = str(client_order_index)

            logger.info(f"✅ Order placed: {side} {size:.4f} {symbol} @ ${price:.2f} (order_index={order_index}, tx={tx_response.tx_hash[:16]}...)")
            logger.debug(f"Order request: {order_result}")

            return order_index

        except Exception as e:
            logger.error(f"Failed to place limit order: {e}")
            logger.error(traceback.format_exc())
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
        if self.client is None:
            await self.initialize()

        # Get market ID and info
        market_id = await self.get_market_id(symbol)
        market_info = await self.get_market_info(symbol)

        # Get current market price
        current_price = await self.get_price(symbol)

        # Use 1% slippage for market-like execution (minimal IL)
        if side.lower() == "buy":
            price = current_price * 1.01  # 1% above market
        else:
            price = current_price * 0.99  # 1% below market

        # Convert size for 1000X markets (e.g., 1000BONK)
        size = self._convert_1000x_size(symbol, size, to_lighter=True)

        # Convert to Lighter's integer format
        is_ask = side.lower() == "sell"
        base_amount = int(size * market_info["base_multiplier"])
        price_int = int(price * market_info["price_multiplier"])

        # Generate client order ID
        client_order_index = int(time.time() * 1000) % 1000000

        try:
            # Use regular limit order with 1% slippage for market execution
            order_params = {
                'market_index': market_id,
                'client_order_index': client_order_index,
                'base_amount': base_amount,
                'price': price_int,
                'is_ask': is_ask,
                'order_type': self.client.ORDER_TYPE_LIMIT,
                'time_in_force': self.client.ORDER_TIME_IN_FORCE_GOOD_TILL_TIME,
                'reduce_only': False,
                'trigger_price': 0,
            }

            order_result, tx_response, error = await self.client.create_order(**order_params)

            if error:
                logger.error(f"Market order failed: {error}")
                raise Exception(f"Market order failed: {error}")

            # Log the actual API response
            logger.info(f"📡 API Response: code={tx_response.code}, message={tx_response.message}, tx_hash={tx_response.tx_hash}")

            # Check response code
            if tx_response.code != 200:
                logger.error(f"Market order rejected: code={tx_response.code}, message={tx_response.message}")
                raise Exception(f"Order rejected: {tx_response.message or 'Unknown error'}")

            # For cancellation, use the client_order_index we generated
            order_index = str(client_order_index)

            logger.info(f"✅ Market order: {side} {size:.4f} {symbol} @ ~${current_price:.2f} (order_index={order_index}, tx={tx_response.tx_hash[:16]}...)")

            return order_index

        except Exception as e:
            logger.error(f"Failed to place market order: {e}")
            logger.error(traceback.format_exc())
            raise

    async def cancel_order(self, symbol: str, order_index: str) -> bool:
        """
        Cancel an order

        Args:
            symbol: Market symbol (e.g., "SOL", "BTC")
            order_index: The client_order_index used when creating the order

        Returns:
            True if successful
        """
        if self.client is None:
            await self.initialize()

        try:
            market_id = await self.get_market_id(symbol)

            # Convert order_index to integer (it should be the client_order_index from creation)
            try:
                order_index_int = int(order_index)
            except ValueError:
                logger.error(f"Invalid order_index format: {order_index} (expected integer)")
                return False

            # Use the correct parameter name: order_index (not order_id)
            cancel_result, tx_response, error = await self.client.cancel_order(
                market_index=market_id,
                order_index=order_index_int
            )

            if error:
                logger.error(f"Order cancellation failed: {error}")
                raise Exception(f"Order cancellation failed: {error}")

            # Log response
            logger.info(f"📡 Cancel Response: code={tx_response.code}, message={tx_response.message}")

            if tx_response.code != 200:
                logger.error(f"Cancellation rejected: code={tx_response.code}, message={tx_response.message}")
                return False

            logger.info(f"✅ Order canceled: order_index={order_index}, tx={tx_response.tx_hash[:16]}...")
            return True

        except Exception as e:
            logger.error(f"Failed to cancel order {order_index}: {e}")
            logger.error(traceback.format_exc())
            return False
