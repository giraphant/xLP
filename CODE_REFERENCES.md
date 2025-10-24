# Stateless & Atomic Design - Specific Code References

## Quick Navigation

This document provides line-by-line references for all key architectural patterns in the xLP codebase.

---

## 1. PIPELINE ARCHITECTURE

### Entry Point: Main Loop
**File**: `/home/xLP/src/main.py`

```python
# Lines 31-81
async def main():
    engine = HedgeEngine()
    error_count = 0
    max_errors = 10
    
    while True:
        try:
            await engine.run_once()  # Single cycle execution
            error_count = 0
            await asyncio.sleep(interval)
        except Exception as e:
            error_count += 1
            if error_count >= max_errors:
                break
```

### Orchestrator: Four-Step Pipeline
**File**: `/home/xLP/src/engine.py`

```python
# Lines 90-147
async def run_once(self):
    # ========== 步骤 1: 准备数据 ==========
    data = await prepare_data(
        self.config,
        self.pool_calculators,
        self.exchange,
        self.cost_history  # Only mutable state passed
    )
    
    # ========== 步骤 2: 决策（完全无状态）==========
    actions = await decide_actions(data, self.config)
    
    # ========== 步骤 3: 执行 ==========
    results = await execute_actions(actions, self.exchange, self.notifier)
    
    # ========== 步骤 4: 报告 ==========
    await generate_reports(data, results, self.config, self.matsu_reporter)
```

---

## 2. MUTABLE STATE: cost_history

### Initialization
**File**: `/home/xLP/src/engine.py`
**Lines**: 41-67

```python
class HedgeEngine:
    def __init__(self):
        self.config = HedgeConfig()
        self.exchange = create_exchange(config_dict["exchange"])
        self.notifier = Notifier(config_dict["pushover"])
        self.matsu_reporter = self._initialize_matsu_reporter()
        
        self.pool_calculators = {
            "jlp": jlp.calculate_hedge,
            "alp": alp.calculate_hedge
        }
        
        # ⭐ ONLY MUTABLE STATE
        self.cost_history = {}  # {symbol: (offset, cost_basis)}
```

### Usage: Read-Compute-Write Pattern
**File**: `/home/xLP/src/core/prepare.py`
**Lines**: 254-267

```python
# Function: _calculate_offsets()
for symbol in ideal_hedges:
    # Step 1: READ from cost_history
    old_offset, old_cost = cost_history.get(symbol, (0.0, 0.0))
    
    # Step 2: PURE COMPUTATION (no state)
    offset, cost = calculate_offset_and_cost(
        ideal_hedges[symbol],
        positions.get(symbol, 0.0),
        prices[symbol],
        old_offset,    # Pass as parameter, not fetch from state
        old_cost
    )
    
    # Step 3: ATOMIC WRITE
    cost_history[symbol] = (offset, cost)
    offsets[symbol] = (offset, cost)
```

---

## 3. PURE FUNCTIONS: Calculation Core

### Pure Function 1: Cost Calculation
**File**: `/home/xLP/src/utils/calculators/offset.py`
**Lines**: 11-91

```python
def calculate_offset_and_cost(
    ideal_position: float,
    actual_position: float,
    current_price: float,
    old_offset: float,
    old_cost: float
) -> Tuple[float, float]:
    """Pure function: deterministic, no side effects"""
    
    # Input validation (lines 47-56)
    if current_price <= 0:
        raise ValueError(...)
    if not all(math.isfinite(x) for x in [...]):
        raise ValueError(...)
    
    # Core calculation (lines 58-83)
    new_offset = actual_position - ideal_position
    delta_offset = new_offset - old_offset
    
    # Edge cases (lines 65-74)
    if abs(delta_offset) < 1e-8:
        return new_offset, old_cost
    if abs(new_offset) < 1e-8:
        return 0.0, 0.0
    if abs(old_offset) < 1e-8:
        return new_offset, current_price
    
    # Unified formula (line 83)
    new_cost = (old_offset * old_cost + delta_offset * current_price) / new_offset
    
    return new_offset, new_cost
```

**Properties**:
- ✅ No side effects
- ✅ No external dependencies  
- ✅ All inputs explicit (5 parameters)
- ✅ Output deterministic
- ✅ Edge cases handled (4+)

### Pure Function 2: Zone Calculation
**File**: `/home/xLP/src/utils/calculators/zone.py`
**Lines**: 9-38

```python
def calculate_zone(
    offset_usd: float,
    min_threshold: float,
    max_threshold: float,
    step: float
) -> Optional[int]:
    """Pure function: deterministic zone mapping"""
    
    abs_usd = abs(offset_usd)
    
    if abs_usd < min_threshold:
        return None
    
    if abs_usd > max_threshold:
        return -1  # Alert
    
    zone = int((abs_usd - min_threshold) / step)
    return zone
```

**Properties**:
- ✅ Single input → single output
- ✅ No state dependency
- ✅ Deterministic

### Pure Function 3: Order Parameters
**File**: `/home/xLP/src/utils/calculators/order.py`
**Lines**: 8-39

```python
def calculate_close_size(offset: float, close_ratio: float) -> float:
    """Pure: calculates position size"""
    return abs(offset) * (close_ratio / 100.0)

def calculate_limit_price(
    offset: float,
    cost_basis: float,
    price_offset_percent: float
) -> float:
    """Pure: calculates order price"""
    if offset > 0:
        return cost_basis * (1 + price_offset_percent / 100)
    else:
        return cost_basis * (1 - price_offset_percent / 100)
```

**Properties**:
- ✅ Atomic (one parameter each)
- ✅ Reversible/testable
- ✅ No dependencies

---

## 4. DECISION LOGIC: Pure Decision Engine

### Entry Point
**File**: `/home/xLP/src/core/decide.py`
**Lines**: 48-119

```python
async def decide_actions(
    data: Dict[str, Any],       # All from prepare (immutable)
    config: HedgeConfig
) -> List[TradingAction]:
    """Pure decision function: no state mutations"""
    
    logger.info("=" * 50)
    logger.info("🤔 DECISION MAKING")
    logger.info("=" * 50)
    
    all_actions = []
    
    # Process each symbol (lines 79-110)
    for symbol in data["symbols"]:
        if symbol not in data["offsets"] or symbol not in data["zones"]:
            continue
        
        # Get all data (lines 85-94)
        offset, cost_basis = data["offsets"][symbol]
        price = data["prices"][symbol]
        zone_info = data["zones"][symbol]
        zone = zone_info["zone"]
        offset_usd = zone_info["offset_usd"]
        
        order_info = data.get("order_status", {}).get(symbol, {})
        last_fill_time = data.get("last_fill_times", {}).get(symbol)
        previous_zone = order_info.get("previous_zone")
        
        # Call pure decision function (lines 97-108)
        actions = _decide_symbol_actions_v2(
            symbol=symbol,
            offset=offset,
            cost_basis=cost_basis,
            current_price=price,
            offset_usd=offset_usd,
            zone=zone,
            previous_zone=previous_zone,
            order_info=order_info,
            last_fill_time=last_fill_time,
            config=config
        )
        
        all_actions.extend(actions)
    
    return all_actions
```

### Decision Function with Decision Tree
**File**: `/home/xLP/src/core/decide.py`
**Lines**: 154-329

```python
def _decide_symbol_actions_v2(
    symbol: str,
    offset: float,
    cost_basis: float,
    current_price: float,
    offset_usd: float,
    zone: Optional[int],
    previous_zone: Optional[int],
    order_info: Dict[str, Any],
    last_fill_time: Optional[datetime],
    config: Dict[str, Any]
) -> List[TradingAction]:
    """Pure decision logic: 5-level priority tree"""
    
    actions = []
    has_active_order = order_info.get("has_order", False)
    oldest_order_time = order_info.get("oldest_order_time")
    
    # ========== 决策1: 超阈值检查 ========== (lines 192-213)
    if zone == -1:
        logger.warning(f"{symbol}: ⚠️ Exceeded max threshold ${offset_usd:.2f}")
        
        if has_active_order:
            actions.append(TradingAction(
                type=ActionType.CANCEL_ORDER,
                symbol=symbol,
                reason="Exceeded max threshold"
            ))
        
        actions.append(TradingAction(
            type=ActionType.ALERT,
            symbol=symbol,
            reason=f"Threshold exceeded: ${offset_usd:.2f}",
            metadata={...}
        ))
        return actions
    
    # ========== 决策2: 超时检查 ========== (lines 216-245)
    if has_active_order and oldest_order_time:
        elapsed_minutes = (datetime.now() - oldest_order_time).total_seconds() / 60
        if elapsed_minutes >= config.timeout_minutes:
            logger.warning(f"{symbol}: ⏰ Order timeout after {elapsed_minutes:.1f} minutes")
            
            actions.append(TradingAction(
                type=ActionType.CANCEL_ORDER,
                symbol=symbol,
                reason=f"Timeout after {elapsed_minutes:.1f} minutes"
            ))
            
            order_size = calculate_close_size(offset, config.close_ratio)
            side = "sell" if offset > 0 else "buy"
            
            actions.append(TradingAction(
                type=ActionType.PLACE_MARKET_ORDER,
                symbol=symbol,
                side=side,
                size=order_size,
                reason="Force close due to timeout",
                metadata={"force_close": True, ...}
            ))
            return actions
    
    # ========== 决策3: Zone恶化强制重新下单 ========== (lines 248-259)
    if has_active_order and previous_zone is not None and zone is not None and zone > previous_zone:
        logger.info(f"{symbol}: 📈 Zone worsened: {previous_zone} → {zone}, forcing re-order")
        actions.append(TradingAction(
            type=ActionType.CANCEL_ORDER,
            symbol=symbol,
            reason=f"Zone worsened: {previous_zone} → {zone}"
        ))
        actions.append(_create_limit_order_action(
            symbol, offset, offset_usd, cost_basis, zone,
            f"Re-order due to zone worsening", config
        ))
        return actions
    
    # ========== 决策4: 有敞口 - 订单管理 ========== (lines 262-302)
    if zone is not None:
        # Check cooldown (lines 264-272)
        in_cooldown = False
        if last_fill_time:
            elapsed = (datetime.now() - last_fill_time).total_seconds() / 60
            in_cooldown = elapsed < config.cooldown_after_fill_minutes
        
        # If in cooldown (lines 275-283)
        if in_cooldown:
            reason = f"In cooldown period (...)" if not has_active_order else f"Maintaining order in cooldown (zone: {zone})"
            logger.info(f"{symbol}: 🧊 {reason}")
            return [TradingAction(
                type=ActionType.NO_ACTION,
                symbol=symbol,
                reason=reason,
                metadata={"in_cooldown": True, "zone": zone, "has_order": has_active_order}
            )]
        
        # If no active order (lines 286-293)
        if not has_active_order:
            logger.info(f"{symbol}: 📍 Entering zone {zone}, placing order")
            action = _create_limit_order_action(
                symbol, offset, offset_usd, cost_basis, zone,
                f"Entering zone {zone}", config
            )
            logger.info(f"{symbol}: Placing {action.side} order for {action.size:.4f} @ ${action.price:.2f}")
            return [action]
        
        # Default: maintain order (lines 296-302)
        logger.debug(f"{symbol}: Order active in zone {zone}, maintaining")
        return [TradingAction(
            type=ActionType.NO_ACTION,
            symbol=symbol,
            reason=f"Maintaining order in zone {zone}",
            metadata={"zone": zone, "has_order": True}
        )]
    
    # ========== 决策5: 无敞口 - 清理状态 ========== (lines 305-321)
    if zone is None:
        if has_active_order:
            logger.info(f"{symbol}: ✅ Back to safe zone, canceling order")
            return [TradingAction(
                type=ActionType.CANCEL_ORDER,
                symbol=symbol,
                reason="Back within threshold"
            )]
        else:
            logger.debug(f"{symbol}: Within threshold, no action needed")
            return [TradingAction(
                type=ActionType.NO_ACTION,
                symbol=symbol,
                reason="Within threshold"
            )]
    
    return [TradingAction(
        type=ActionType.NO_ACTION,
        symbol=symbol,
        reason="Unexpected decision tree end"
    )]
```

**Properties**:
- ✅ Pure (no state mutations)
- ✅ Deterministic (same input → same output)
- ✅ All parameters explicit
- ✅ Comprehensive (5 decision priorities)
- ✅ Well-tested (420+ test lines)

---

## 5. EXECUTION: Side Effects Isolated

### Execution Orchestrator
**File**: `/home/xLP/src/core/execute.py`
**Lines**: 19-94

```python
async def execute_actions(
    actions: List[TradingAction],  # From decide (immutable)
    exchange,                       # I/O interface
    notifier                        # I/O interface
) -> List[Dict[str, Any]]:
    """Execute: side effects isolated, results returned"""
    
    logger.info("=" * 50)
    logger.info("⚡ EXECUTING ACTIONS")
    logger.info("=" * 50)
    
    if not actions:
        logger.info("No actions to execute")
        return []
    
    results = []
    
    for action in actions:
        try:
            result = {"action": action, "success": False}
            
            # 限价单 (lines 52-57)
            if action.type == ActionType.PLACE_LIMIT_ORDER:
                order_id = await _execute_limit_order(action, exchange)
                result["success"] = True
                result["order_id"] = order_id
            
            # 市价单 (lines 60-65)
            elif action.type == ActionType.PLACE_MARKET_ORDER:
                order_id = await _execute_market_order(action, exchange, notifier)
                result["success"] = True
                result["order_id"] = order_id
            
            # 撤销 (lines 68-72)
            elif action.type == ActionType.CANCEL_ORDER:
                success = await _execute_cancel_order(action, exchange)
                result["success"] = success
            
            # 警报 (lines 75-77)
            elif action.type == ActionType.ALERT:
                await _execute_alert(action, notifier)
                result["success"] = True
            
            # 无操作 (lines 80-82)
            elif action.type == ActionType.NO_ACTION:
                logger.debug(f"⏭️  No action: {action.symbol} - {action.reason}")
                result["success"] = True
            
            results.append(result)
        
        except Exception as e:
            logger.error(f"Failed to execute {action.type.value} for {action.symbol}: {e}")
            results.append({"action": action, "success": False, "error": str(e)})
    
    success_count = sum(1 for r in results if r["success"])
    logger.info(f"✅ Executed {success_count}/{len(results)} actions successfully")
    
    return results
```

**Properties**:
- ✅ Decision → Execution separation
- ✅ Command pattern (actions pre-described)
- ✅ Results tracked per action
- ✅ Failures isolated

---

## 6. CONFIGURATION: Immutable & Validated

**File**: `/home/xLP/src/utils/config.py`
**Lines**: 72-154

```python
class HedgeConfig(BaseSettings):
    """Immutable configuration"""
    
    # Pool (lines 81-82)
    jlp_amount: float = Field(default=0.0, ge=0)
    alp_amount: float = Field(default=0.0, ge=0)
    
    # Thresholds (lines 85-87)
    threshold_min_usd: float = Field(default=5.0, gt=0)
    threshold_max_usd: float = Field(default=20.0, gt=0)
    threshold_step_usd: float = Field(default=2.5, gt=0)
    
    # Timing & Ratios (lines 90-94)
    check_interval_seconds: int = Field(default=60, ge=1)
    timeout_minutes: int = Field(default=20, ge=1)
    order_price_offset: float = Field(default=0.2, ge=0, le=10)
    close_ratio: float = Field(default=40.0, gt=0, le=100)
    cooldown_after_fill_minutes: int = Field(default=5, ge=0)
    
    # ... more fields ...
    
    # Pydantic Settings (lines 124-130)
    model_config = SettingsConfigDict(
        env_file='.env',
        env_file_encoding='utf-8',
        case_sensitive=False,
        extra='ignore',
        populate_by_name=True,
    )
    
    # Validation (lines 132-154)
    @model_validator(mode='after')
    def validate_config(self):
        # Threshold validation (lines 135-137)
        if self.threshold_min_usd >= self.threshold_max_usd:
            raise ValueError(...)
        
        # Step validation (lines 139-141)
        num_steps = (self.threshold_max_usd - self.threshold_min_usd) / self.threshold_step_usd
        if num_steps > 100:
            logger.warning(...)
        
        # Pool validation (lines 144-145)
        if self.jlp_amount == 0 and self.alp_amount == 0:
            logger.warning(...)
        
        # Offset validation (lines 148-152)
        offsets = {'SOL': self.initial_offset_sol, ...}
        large = [f"{s}={v}" for s, v in offsets.items() if abs(v) > 1000]
        if large:
            logger.warning(...)
        
        return self
```

**Properties**:
- ✅ Environment variable driven
- ✅ Type-safe (Pydantic)
- ✅ Validated at init
- ✅ Read-only after init

---

## 7. DATA FLOW: One-Way Pipeline

### Complete Flow
**File**: `/home/xLP/src/engine.py`
**Lines**: 103-129

```python
# Step 1: DATA PREPARATION (lines 103-108)
data = await prepare_data(
    self.config,
    self.pool_calculators,
    self.exchange,
    self.cost_history  # Only mutable state
)
# Returns: {
#     "symbols": [...],
#     "ideal_hedges": {...},
#     "positions": {...},
#     "prices": {...},
#     "offsets": {...},
#     "zones": {...},
#     "order_status": {...},
#     "last_fill_times": {...}
# }

# Step 2: PURE DECISION (lines 111-114)
actions = await decide_actions(data, self.config)
# Returns: List[TradingAction]

# Step 3: EXECUTION (lines 117-121)
results = await execute_actions(
    actions,
    self.exchange,
    self.notifier
)
# Returns: List[Dict with success/error]

# Step 4: REPORTING (lines 124-129)
await generate_reports(
    data,
    results,
    self.config,
    self.matsu_reporter
)
# Returns: Nothing (logging only)
```

**Data Immutability**:
- ✅ `data` dict created in step 1, never modified
- ✅ `actions` list created in step 2, only read in step 3
- ✅ `results` list created in step 3, only read in step 4
- ✅ No feedback loops

---

## 8. DATACLASS: Command Pattern

**File**: `/home/xLP/src/core/decide.py`
**Lines**: 23-45

```python
class ActionType(Enum):
    """Action types"""
    PLACE_LIMIT_ORDER = "place_limit_order"
    PLACE_MARKET_ORDER = "place_market_order"
    CANCEL_ORDER = "cancel_order"
    NO_ACTION = "no_action"
    ALERT = "alert"

@dataclass
class TradingAction:
    """Command object describing an action"""
    type: ActionType
    symbol: str
    side: Optional[str] = None          # "buy"/"sell"
    size: Optional[float] = None
    price: Optional[float] = None
    reason: str = ""
    metadata: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}
```

**Properties**:
- ✅ Command pattern
- ✅ Immutable by convention
- ✅ Can be inspected before execution
- ✅ Audit trail

---

## 9. TESTING: Comprehensive

**File**: `/home/xLP/tests/core/test_decide.py`
**Lines**: 1-476

```python
# Test fixtures (lines 26-37)
@pytest.fixture
def mock_config():
    """Standard test configuration"""
    return HedgeConfig(
        threshold_min_usd=5.0,
        threshold_max_usd=20.0,
        threshold_step_usd=2.5,
        timeout_minutes=20,
        order_price_offset=0.2,
        close_ratio=40.0,
        cooldown_after_fill_minutes=5
    )

# Test classes:
# - TestZoneCalculation (lines 51-113) - 7 tests
# - TestCooldownLogic (lines 116-214) - 5 tests
# - TestDecisionLogic (lines 216-418) - 9 tests
# - TestLimitOrderCalculation (lines 420-472) - 2 tests

# Example test (lines 54-62)
def test_below_min_threshold(self, mock_config):
    """Low below minimum threshold -> None"""
    zone = calculate_zone(
        offset_usd=3.0,
        min_threshold=5.0,
        max_threshold=20.0,
        step=2.5
    )
    assert zone is None
```

**Coverage**:
- ✅ 420+ lines of tests
- ✅ Pure functions easily testable
- ✅ Zone calculations tested
- ✅ Decision tree tested
- ✅ Order parameters tested

---

## 10. EXCHANGE INTERFACE: Stateless

**File**: `/home/xLP/src/exchanges/interface.py`
**Lines**: 10-164

```python
class ExchangeInterface(ABC):
    """Abstract exchange interface"""
    
    def __init__(self, config: dict):
        self.config = config
        self.name = config["name"]
    
    # Query methods (read-only, idempotent)
    @abstractmethod
    async def get_position(self, symbol: str) -> float:
        """Get current position (read-only query)"""
        pass
    
    @abstractmethod
    async def get_price(self, symbol: str) -> float:
        """Get current price (read-only query)"""
        pass
    
    @abstractmethod
    async def get_open_orders(self, symbol: str = None) -> list:
        """Get open orders (fresh query each time)"""
        pass
    
    @abstractmethod
    async def get_recent_fills(self, symbol: str = None, minutes_back: int = 10) -> list:
        """Get recent fills (fresh query each time)"""
        pass
    
    # Command methods (idempotent/retryable)
    @abstractmethod
    async def place_limit_order(self, symbol: str, side: str, size: float, price: float) -> str:
        """Place limit order"""
        pass
    
    @abstractmethod
    async def place_market_order(self, symbol: str, side: str, size: float) -> str:
        """Place market order"""
        pass
    
    @abstractmethod
    async def cancel_order(self, order_id: str) -> bool:
        """Cancel single order"""
        pass
    
    @abstractmethod
    async def cancel_all_orders(self, symbol: str) -> int:
        """Cancel all orders for symbol"""
        pass
```

**Properties**:
- ✅ Stateless from caller perspective
- ✅ Query methods return current state
- ✅ Commands are idempotent/retryable
- ✅ Each cycle queries fresh

---

## Summary Table

| Aspect | File | Lines | Property |
|--------|------|-------|----------|
| **Pipeline** | `engine.py` | 90-147 | 4-step pure composition |
| **Mutable State** | `engine.py` | 66-67 | One dict: cost_history |
| **Cost Calculation** | `calculators/offset.py` | 11-91 | Pure function |
| **Zone Calculation** | `calculators/zone.py` | 9-38 | Pure function |
| **Decision Engine** | `core/decide.py` | 154-329 | Pure logic (5 priorities) |
| **Execution** | `core/execute.py` | 19-94 | Side effects isolated |
| **Configuration** | `utils/config.py` | 72-154 | Immutable + validated |
| **Data Flow** | `engine.py` | 103-129 | One-way, no loops |
| **Commands** | `core/decide.py` | 23-45 | Dataclass pattern |
| **Tests** | `tests/core/test_decide.py` | 1-476 | 420+ lines coverage |
| **Exchange** | `exchanges/interface.py` | 10-164 | Stateless interface |

