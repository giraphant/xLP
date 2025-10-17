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
├── src/                           # Core source code
│   ├── main.py                   # Main loop with error handling
│   ├── hedge_engine.py           # Hedge engine orchestrator
│   │
│   ├── core/                     # 🎯 Core Business Logic
│   │   ├── pipeline.py           # Data processing pipeline
│   │   ├── decision_engine.py    # Trading decision logic
│   │   ├── action_executor.py    # Order execution engine
│   │   ├── offset_tracker.py     # ⭐ Atomic cost tracking
│   │   ├── state_manager.py      # Position & order state
│   │   └── exceptions.py         # Business exceptions
│   │
│   ├── utils/                    # 🔧 Utilities
│   │   ├── config_validator.py   # Configuration validation
│   │   ├── circuit_breaker.py    # Failure protection
│   │   └── logging_utils.py      # Sensitive data masking
│   │
│   ├── monitoring/               # 📊 Observability
│   │   ├── metrics.py            # Performance metrics
│   │   └── reports.py            # Position reports & PnL
│   │
│   ├── pools/                    # LP pool calculators
│   │   ├── jlp.py               # JLP pool hedge calculator
│   │   └── alp.py               # ALP pool hedge calculator
│   │
│   ├── exchanges/                # Exchange integrations
│   │   ├── interface.py         # Exchange abstraction
│   │   └── lighter.py           # Lighter DEX integration
│   │
│   └── notifications/            # Alert system
│       └── pushover.py          # Pushover notifications
│
├── tests/                        # Test suite
├── docs/                         # Documentation
├── Dockerfile                    # Container image
├── docker-compose.yml            # One-command deployment
├── .env.example                 # Environment template
└── config.json                  # Configuration (optional)
```

## Key Features

### 1. Pipeline Architecture

Modular data processing with clear separation of concerns:
- **FetchPoolData** → **CalculateIdealHedges** → **FetchMarketData**
- **CalculateOffsets** → **ApplyPredefinedOffset** → **DecideActions** → **ExecuteActions**

Each step is independently testable with built-in retry logic and timeout protection.

### 2. On-Chain Data Parsing

Both JLP and ALP hedge calculators read directly from Solana blockchain:
- Binary parsing at specific account offsets
- Oracle integration for price data (ALP)
- JITOSOL → SOL conversion (ALP)
- WBTC → BTC unification

### 3. Atomic Cost Tracking

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

### 4. External Hedge Adjustment

Support for external hedges or intentional exposure via **predefined offsets**:
```bash
# Already hedged 1 SOL on Binance, reduce system hedge by 1
PREDEFINED_OFFSET_SOL=-1.0
PREDEFINED_OFFSET_BTC=0.05
```

### 5. Advanced Safety & Monitoring

- **Circuit Breaker**: Prevents cascading failures with automatic cooldown
- **Metrics Collection**: Track success rates, latency, error patterns
- **Detailed Reports**: Position PnL, cost basis, decision process logging
- **Sensitive Data Masking**: Automatic private key obfuscation in logs

### 6. Dynamic Threshold System

Zone-based triggering with USD absolute values:
- Configurable min/max/step thresholds
- Automatic limit order placement at cost basis
- Timeout-based forced market closure
- Per-symbol monitoring state

### 7. Unified Symbol Tracking

Positions tracked by symbol (SOL, ETH, BTC, BONK), not by pool. JLP and ALP positions are automatically merged.

## Quick Start

**🐳 Recommended: Docker Deployment** (see [docs/QUICKSTART.md](docs/QUICKSTART.md))

```bash
# 1. Clone and configure
git clone https://github.com/giraphant/xLP.git
cd xLP
cp .env.example .env
nano .env  # Fill in your settings

# 2. Start with one command
mkdir -p data logs
docker-compose up -d

# 3. Monitor
docker-compose logs -f
```

### Configuration (Environment Variables)

**All configuration via `.env` file** (12-factor app compliant):

**Optional**: You can also create `config.json` from the example template, but environment variables take priority.

```env
# ===== Required =====
EXCHANGE_NAME=lighter
EXCHANGE_PRIVATE_KEY=your_lighter_private_key
JLP_AMOUNT=100
ALP_AMOUNT=0

# ===== Thresholds (USD absolute values) =====
THRESHOLD_MIN_USD=5.0
THRESHOLD_MAX_USD=20.0
THRESHOLD_STEP_USD=2.5

# ===== Order Execution =====
ORDER_PRICE_OFFSET=0.2        # Limit order offset (%)
CLOSE_RATIO=40.0              # Partial close percentage
TIMEOUT_MINUTES=20            # Order timeout before forced market close
CHECK_INTERVAL_SECONDS=60     # Main loop interval

# ===== External Hedge Adjustment (Optional) =====
# Adjust for hedges on other platforms (use separate variables)
PREDEFINED_OFFSET_SOL=-1.0
PREDEFINED_OFFSET_BTC=0.05
PREDEFINED_OFFSET_ETH=0.0

# ===== Initial Position Offset (Optional) =====
# If you have existing positions from before the system started
INITIAL_OFFSET_SOL=0.0
INITIAL_OFFSET_BTC=0.0
INITIAL_OFFSET_ETH=0.0

# ===== Notifications =====
PUSHOVER_USER_KEY=your_user_key
PUSHOVER_API_TOKEN=your_api_token
PUSHOVER_ENABLED=true

# ===== Monitoring =====
ENABLE_DETAILED_REPORTS=true  # Show PnL, cost basis in logs
LOG_LEVEL=INFO                # DEBUG, INFO, WARNING, ERROR
```

> 💡 **Note**: `config.json` is optional. Environment variables take priority.
> 💡 **Thresholds**: Use USD absolute values instead of percentages for simpler, more predictable behavior.
> 💡 **Predefined Offset**: For external hedges. Negative = reduce short, Positive = reduce long.

### Running Tests

```bash
# Run all tests
python tests/test_cost_tracking.py
python tests/test_cost_detailed.py
python tests/test_10_steps.py

# Quick test of atomic module
python src/core/offset_tracker.py
```

### Running the Engine

```bash
# Run once (for testing)
python src/hedge_engine.py

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
- ✅ **Lighter Exchange** - Solana perpetuals DEX (production-ready)
- ✅ **MockExchange** - For testing and development

Test Lighter integration:
```bash
export EXCHANGE_PRIVATE_KEY=your_private_key
python test_lighter.py
```

To add a new exchange, implement the `ExchangeInterface` abstract class in `src/exchange_interface.py`.

## State Management

The system maintains state in `data/state.json` (auto-created from `state_template.json`):

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

Configure via environment variables:
```env
PUSHOVER_USER_KEY=your_user_key
PUSHOVER_API_TOKEN=your_api_token
PUSHOVER_ENABLED=true
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

**Completed:**
- [x] ✅ Lighter exchange integration
- [x] ✅ Docker deployment support
- [x] ✅ Environment-based configuration (12-factor app)
- [x] ✅ Pipeline architecture (modular data processing)
- [x] ✅ Circuit breaker & error handling
- [x] ✅ Metrics collection & monitoring
- [x] ✅ Detailed position reports with PnL
- [x] ✅ External hedge adjustment support
- [x] ✅ Sensitive data masking in logs
- [x] ✅ Type-safe configuration validation

**In Progress:**
- [ ] 🚧 Additional exchanges (Binance, OKX)
- [ ] 🚧 Web dashboard for monitoring

**Planned:**
- [ ] Backtesting framework
- [ ] Multi-account support
- [ ] Advanced risk controls (position limits, max drawdown)
- [ ] Telegram notifications
- [ ] Performance analytics dashboard

## License

MIT

## Disclaimer

This software is provided as-is for educational and research purposes. Use at your own risk. Always test thoroughly before using with real funds.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## Support

For issues and questions, please open an issue on GitHub.
