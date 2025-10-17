# xLP - Solana LP Automated Hedge System

An automated hedge system for Solana liquidity pool tokens (JLP and ALP).

## Overview

This system automatically calculates ideal hedge positions from on-chain data and executes closing logic to maintain hedge balance. It features:

- **Zero External Dependencies**: All pool data parsed directly from Solana blockchain
- **Unified Symbol Tracking**: Tracks positions by symbol (SOL, ETH, BTC, BONK) regardless of pool source
- **Atomic Cost Tracking**: Advanced weighted average cost algorithm with support for all position scenarios
- **Exchange Agnostic**: Abstract interface supports multiple exchanges
- **Configurable Thresholds**: Dynamic zone-based triggering system
- **Smart Order Placement**: Limit orders at cost basis to minimize slippage

## Architecture

```
xLP/
├── src/                    # Core source code
│   ├── JLP_Hedge.py       # JLP pool hedge calculator
│   ├── ALP_Hedge.py       # ALP pool hedge calculator
│   ├── offset_tracker.py  # ⭐ Atomic cost tracking module
│   ├── HedgeEngine.py     # Core hedge engine
│   ├── exchange_interface.py  # Exchange abstraction layer
│   ├── notifier.py        # Pushover notifications
│   └── main.py            # Main loop
├── tests/                  # Test suite
│   ├── test_cost_tracking.py
│   ├── test_cost_detailed.py
│   └── test_10_steps.py
├── docs/                   # Documentation
│   └── ARCHITECTURE.md    # Detailed architecture docs
├── config.json            # Configuration file
└── state_template.json    # State file template
```

## Key Features

### 1. On-Chain Data Parsing

Both JLP and ALP hedge calculators read directly from Solana blockchain:
- Binary parsing at specific account offsets
- Oracle integration for price data (ALP)
- JITOSOL → SOL conversion (ALP)
- WBTC → BTC unification

### 2. Atomic Cost Tracking

The `offset_tracker.py` module implements a unified formula that handles all scenarios:

```python
new_cost = (old_offset × old_cost + delta_offset × current_price) / new_offset
```

This single formula correctly handles:
- ✅ Initial position establishment
- ✅ Position expansion (weighted average)
- ✅ Position reduction (cost adjustment)
- ✅ Complete closure (reset to zero)
- ✅ Direction reversal (long ↔ short)

### 3. Dynamic Threshold System

Zone-based triggering:
- Minimum threshold: 1%
- Maximum threshold: 2%
- Step size: 0.2%
- Automatic limit order placement
- 20-minute timeout with forced market close

### 4. Unified Symbol Tracking

Positions tracked by symbol (SOL, ETH, BTC, BONK), not by pool. JLP and ALP positions are automatically merged.

## Quick Start

### Installation

```bash
# Clone the repository
git clone https://github.com/YOUR_USERNAME/xLP.git
cd xLP

# Install dependencies
pip install httpx  # For notifications (optional)

# Copy and configure
cp config.json config.local.json
# Edit config.local.json with your settings
```

### Configuration

Edit `config.json`:

```json
{
  "jlp_amount": 50000,        // Your JLP holdings
  "alp_amount": 10000,        // Your ALP holdings
  "threshold_min": 1.0,       // Min threshold %
  "threshold_max": 2.0,       // Max threshold %
  "threshold_step": 0.2,      // Zone step size %
  "order_price_offset": 0.2,  // Limit order offset %
  "close_ratio": 40.0,        // Close % per trigger
  "timeout_minutes": 20       // Timeout before forced close
}
```

### Running Tests

```bash
# Run all tests
python tests/test_cost_tracking.py
python tests/test_cost_detailed.py
python tests/test_10_steps.py

# Quick test of atomic module
python src/offset_tracker.py
```

### Running the Engine

```bash
# Run once (for testing)
python src/HedgeEngine.py

# Run main loop (production)
python src/main.py
```

## Core Algorithm

The cost tracking algorithm is the heart of the system. It maintains weighted average cost across all position changes:

**Scenario: Long Exposure Expansion**
```
Position: 50 → 55 (add 5)
Old cost: $200
Current price: $210
New cost: (50 × 200 + 5 × 210) / 55 = $200.91
```

**Scenario: Position Reduction**
```
Position: 60 → 40 (close 20)
Old cost: $202.50
Close price: $225
New cost: (60 × 202.50 + (-20) × 225) / 40 = $196.25
Realized P&L: 20 × (225 - 202.50) = +$450
```

See `tests/test_10_steps.py` for a complete walkthrough.

## Exchange Integration

Currently supports:
- ✅ MockExchange (for testing)
- 🚧 LighterExchange (in development)

To add a new exchange, implement the `ExchangeInterface` abstract class in `src/exchange_interface.py`.

## State Management

The system maintains state in `state.json` (auto-created from template):

```json
{
  "symbols": {
    "SOL": {
      "offset": 609.24,
      "cost_basis": 200.0,
      "last_updated": "2025-10-16T23:21:40",
      "monitoring": {
        "active": false,
        "current_zone": null,
        "order_id": null
      }
    }
  }
}
```

## Notifications

Pushover integration for:
- ⚠️ Threshold exceeded alerts
- 🔔 Forced close notifications
- 📊 Order placement updates (optional)

Configure in `config.json`:
```json
{
  "pushover": {
    "user_key": "YOUR_USER_KEY",
    "api_token": "YOUR_API_TOKEN"
  }
}
```

## Documentation

- [ARCHITECTURE.md](docs/ARCHITECTURE.md) - Detailed architecture documentation
- [Test Suite](tests/) - Comprehensive test cases with explanations

## Safety Features

- Read-only on-chain data parsing
- Configurable position limits
- Timeout-based forced closure
- Alert system for threshold violations
- State persistence for crash recovery

## Roadmap

- [ ] Complete Lighter exchange integration
- [ ] Add support for additional exchanges (Binance, OKX)
- [ ] Structured logging system
- [ ] Additional risk controls
- [ ] Backtesting framework
- [ ] Web dashboard

## License

MIT

## Disclaimer

This software is provided as-is for educational and research purposes. Use at your own risk. Always test thoroughly before using with real funds.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## Support

For issues and questions, please open an issue on GitHub.
