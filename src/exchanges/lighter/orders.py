#!/usr/bin/env python3
"""
Lighter Exchange - Order operations (limit, market, cancel)
"""

import time
import logging
import traceback

from .market import LighterMarketManager
from .types import MIN_ORDER_VALUE_USD
from .utils import convert_1000x_size

logger = logging.getLogger(__name__)


class LighterOrderManager(LighterMarketManager):
    """Manages order operations for Lighter exchange"""

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

        # Save original values for USD calculation (before conversion)
        original_size = size
        original_price = price

        # Convert size for 1000X markets (e.g., 1000BONK)
        size = convert_1000x_size(symbol, size, to_lighter=True)

        # Convert price for 1000X markets
        # For 1000BONK: price comes in as per-BONK ($0.000015), but Lighter needs per-1000BONK ($0.015)
        if symbol.startswith("1000"):
            price = price * 1000

        # Convert to Lighter's integer format
        is_ask = side.lower() == "sell"
        base_amount = int(size * market_info["base_multiplier"])
        price_int = int(price * market_info["price_multiplier"])

        # Log order details for debugging
        logger.info(f"📝 Limit Order calculation for {symbol}:")
        logger.info(f"  Size: {size:.8f} {symbol}")
        logger.info(f"  Base multiplier: {market_info['base_multiplier']} (decimals: {market_info['size_decimals']})")
        logger.info(f"  BaseAmount (integer): {base_amount}")
        logger.info(f"  Price: ${price:.6f}, Price int: {price_int}")

        # Calculate order value in USD using ORIGINAL values (before conversions)
        order_value_usd = original_size * original_price
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
            logger.error(f"Full traceback:\n{traceback.format_exc()}")
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
            symbol: Market symbol (e.g., "SOL")
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

        # Get current market price (already adjusted for 1000X markets by get_price)
        current_price = await self.get_price(symbol)

        # Use 0.2% slippage for market-like execution (minimal IL)
        if side.lower() == "buy":
            price = current_price * 1.002  # 0.2% above market
        else:
            price = current_price * 0.998  # 0.2% below market

        # Convert size for 1000X markets (e.g., 1000BONK)
        size = convert_1000x_size(symbol, size, to_lighter=True)

        # Convert price for 1000X markets
        # For 1000BONK: price is per-BONK ($0.000015), but Lighter needs per-1000BONK ($0.015)
        if symbol.startswith("1000"):
            price = price * 1000

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
