# xLP - Solana LP Automated Hedge System

An automated hedge system for Solana liquidity pool tokens (JLP and ALP).

## Overview

This system automatically calculates ideal hedge positions from on-chain data and executes trades to maintain hedge balance. It features:

- **Zero External Dependencies**: All pool data parsed directly from Solana blockchain
- **Unified Symbol Tracking**: Tracks positions by symbol (SOL, ETH, BTC, BONK) regardless of pool source
- **Atomic Cost Tracking**: Weighted average cost algorithm with support for all position scenarios
- **Exchange Agnostic**: Abstract interface supports multiple exchanges
- **Zone-Based Triggering**: Dynamic threshold system with automatic order placement
- **Smart Order Placement**: Limit orders at cost basis to minimize slippage

## Architecture

**Linus-style design**: Simple, direct, and fast.

```
xLP/
├── src/                          # Source code (3162 lines)
│   ├── main.py                   # Entry point
│   ├── hedge_bot.py              # Main coordinator
│   │
│   ├── core/                     # Pure functions (zero dependencies)
│   │   ├── decision_logic.py     # Trading decisions
│   │   ├── zone_calculator.py    # Threshold zones
│   │   ├── order_calculator.py   # Order price/size
│   │   ├── offset_tracker.py     # Cost tracking
│   │   ├── state.py              # Immutable state (frozen dataclass)
│   │   └── exceptions.py         # Business exceptions
│   │
│   ├── adapters/                 # I/O adapters (thin wrappers)
│   │   ├── state_store.py        # State persistence
│   │   └── pool_fetcher.py       # Pool data fetcher
│   │
│   ├── plugins/                  # Optional features (injected via callbacks)
│   │   ├── audit_log.py          # Decision/action logging
│   │   └── metrics.py            # Performance metrics
│   │
│   ├── pools/                    # Pool calculators
│   │   ├── jlp.py                # JLP pool hedge calculator
│   │   └── alp.py                # ALP pool hedge calculator
│   │
│   ├── exchanges/                # Exchange integrations
│   │   ├── interface.py          # Exchange abstraction
│   │   └── lighter.py            # Lighter DEX integration
│   │
│   └── utils/                    # Utilities
│       ├── config.py             # Configuration (env-based)
│       └── exchange_helpers.py   # Stateless exchange functions
│
├── tests/                        # Test suite (84 passed)
├── Dockerfile                    # Container image
├── docker-compose.yml            # One-command deployment
└── config.json                   # Configuration (optional)
```

**Key principles**:
- **Data structures over classes**: Frozen dataclasses, pure functions
- **No unnecessary abstraction**: Direct calls, no wrapper layers
- **Callbacks for plugins**: Audit log and metrics injected via callbacks
- **Synchronous where possible**: No fake async for CPU-bound operations

## Key Features

### 1. Atomic Cost Tracking

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

**Example: Long Exposure Expansion**
```
Position: 50 → 55 (add 5)
Old cost: $200
Current price: $210
New cost: (50 × 200 + 5 × 210) / 55 = $200.91
```

**Example: Position Reduction**
```
Position: 60 → 40 (close 20)
Old cost: $202.50
Close price: $225
New cost: (60 × 202.50 + (-20) × 225) / 40 = $196.25
Realized P&L: 20 × (225 - 202.50) = +$450
```

### 2. On-Chain Data Parsing

Both JLP and ALP hedge calculators read directly from Solana blockchain:
- Binary parsing at specific account offsets
- Oracle integration for price data (ALP)
- JITOSOL → SOL conversion (ALP)
- WBTC → BTC unification

### 3. External Hedge Adjustment

Support for external hedges or intentional exposure via **predefined offsets**:
```bash
# Already hedged 1 SOL on Binance, reduce system hedge by 1
PREDEFINED_OFFSET_SOL=-1.0
PREDEFINED_OFFSET_BTC=0.05
```

### 4. Zone-Based Threshold System

Dynamic triggering with USD absolute values:
- Configurable min/max/step thresholds
- Automatic limit order placement at cost basis
- Timeout-based forced market closure
- Per-symbol monitoring state
- Cooldown mechanism to prevent rapid re-orders

### 5. Unified Symbol Tracking

Positions tracked by symbol (SOL, ETH, BTC, BONK), not by pool. JLP and ALP positions are automatically merged.

## Quick Start

**🐳 Recommended: Docker Deployment**

```bash
# 1. Clone and configure
git clone https://github.com/giraphant/xLP.git
cd xLP
cp .env.example .env
nano .env  # Fill in your settings

# 2. Start with one command
mkdir -p logs
docker-compose up -d

# 3. Monitor
docker-compose logs -f
```

### Configuration (Environment Variables)

**All configuration via `.env` file** (12-factor app compliant):

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
# Adjust for hedges on other platforms
PREDEFINED_OFFSET_SOL=-1.0
PREDEFINED_OFFSET_BTC=0.05
PREDEFINED_OFFSET_ETH=0.0

# ===== Initial Position Offset (Optional) =====
# If you have existing positions from before the system started
INITIAL_OFFSET_SOL=0.0
INITIAL_OFFSET_BTC=0.0
INITIAL_OFFSET_ETH=0.0

# ===== Monitoring =====
AUDIT_ENABLED=true            # Log decisions/actions to logs/audit.jsonl
LOG_LEVEL=INFO                # DEBUG, INFO, WARNING, ERROR
```

> 💡 **Note**: `config.json` is optional. Environment variables take priority.
> 💡 **Thresholds**: Use USD absolute values for simpler, more predictable behavior.
> 💡 **Predefined Offset**: For external hedges. Negative = reduce short, Positive = reduce long.

### Running Tests

```bash
# Install dependencies
pip install -r requirements.txt

# Run all tests
PYTHONPATH=src pytest tests/ -v

# Quick test of cost tracking
python src/core/offset_tracker.py
```

### Running the Engine

```bash
# Run main loop (production)
python src/main.py

# Or with Docker
docker-compose up -d
```

## Exchange Integration

Currently supports:
- ✅ **Lighter Exchange** - Solana perpetuals DEX (production-ready)
- ✅ **MockExchange** - For testing and development

To add a new exchange, implement the `ExchangeInterface` abstract class in `src/exchanges/interface.py`.

## State Management

The system maintains state using frozen dataclasses with per-symbol locks:

```python
@dataclass(frozen=True)
class SymbolState:
    offset: float = 0.0
    cost_basis: float = 0.0
    last_fill_time: Optional[datetime] = None
    monitoring: MonitoringState = MonitoringState()
```

State is persisted to `data/state.json` for crash recovery.

## Safety Features

- Read-only on-chain data parsing
- Configurable position limits
- Timeout-based forced closure
- Alert system for threshold violations
- State persistence for crash recovery
- Cooldown mechanism to prevent rapid re-orders

## Performance

**Optimizations applied**:
- StateStore: 5-10x throughput (frozen dataclass + threading.Lock)
- Config loading: 15.56x faster (removed pydantic overhead)
- Plugins: 326% faster (removed fake async)
- Code size: -43% (deleted dead code and abstractions)

## Roadmap

**Completed:**
- [x] ✅ Lighter exchange integration
- [x] ✅ Docker deployment support
- [x] ✅ Environment-based configuration (12-factor app)
- [x] ✅ Linus-style refactoring (simple, direct, fast)
- [x] ✅ External hedge adjustment support
- [x] ✅ Cooldown mechanism to prevent rapid order fills
- [x] ✅ Comprehensive test suite (84 tests)

**Planned:**
- [ ] Additional exchanges (Binance, OKX)
- [ ] Web dashboard for monitoring
- [ ] Backtesting framework
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
