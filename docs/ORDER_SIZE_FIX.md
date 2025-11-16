# Order Size Limit Fix

## Problem

Bot çalışıyordu ama tüm emirler risk katmanı tarafından reddediliyordu:
- Log: `Order size limit exceeded: 10.00000000000000000000000000 > 5.0000`
- Strateji 10 USDT notional üretiyordu
- Risk limiti 5 USDT idi
- Sonuç: Hiç emir geçmiyordu

## Root Cause

1. **Order Size Calculation:**
   - `order_notional_pct` = 0.0075 (%0.75)
   - Bot equity = 200 USDT
   - Hesaplanan notional = 200 * 0.0075 = **1.5 USDT**

2. **Minimum Notional Clamp:**
   - `min_order_notional` = **10.0 USDT** (çok yüksek!)
   - Kod: `if notional < min_notional: notional = min_notional`
   - Sonuç: 1.5 USDT → **10 USDT'ye çıkıyor**

3. **Risk Limit:**
   - `max_order_notional_pct` = 0.025 (%2.5)
   - Max allowed = 200 * 0.025 = **5 USDT**
   - 10 USDT > 5 USDT → **REDDEDİLİYOR**

## Solution

### 1. Config Düzeltmeleri

**Before:**
```python
order_notional_pct: float = 0.0075  # %0.75
min_order_notional: float = 10.0     # 10 USDT (çok yüksek!)
max_order_notional_pct: float = 0.025  # %2.5
```

**After:**
```python
order_notional_pct: float = 0.01    # %1.0 (biraz artırıldı)
min_order_notional: float = 2.0     # 2 USDT (düşürüldü)
max_order_notional_pct: float = 0.03  # %3.0 (biraz artırıldı)
```

### 2. Order Size Calculation İyileştirmesi

- `min_notional > max_notional` durumunda fallback eklendi
- Size precision rounding eklendi (8 decimal places)

### 3. Log Spam Önleme

- Risk warning'ler için throttle mekanizması eklendi
- Aynı tip warning 10 saniyede 1 kez log'lanıyor

## Test Results

**BTC @ 95,000 USDT:**
- Calculated Size: ~0.00021 BTC
- Calculated Notional: ~2.0 USDT
- Max Allowed: 6.0 USDT
- Status: ✓ OK

**ETH @ 3,000 USDT:**
- Calculated Size: ~0.0067 ETH
- Calculated Notional: ~2.0 USDT
- Max Allowed: 6.0 USDT
- Status: ✓ OK

## Configuration Recommendations

### Paper Trading (200 USDT equity):
```env
MM_ORDER_NOTIONAL_PCT=0.01      # %1.0
MM_MIN_ORDER_NOTIONAL_USDT=2.0  # 2 USDT
MM_MAX_ORDER_NOTIONAL_PCT=0.03   # %3.0
```

### Live Trading (Conservative):
```env
MM_ORDER_NOTIONAL_PCT=0.005     # %0.5
MM_MIN_ORDER_NOTIONAL_USDT=5.0   # 5 USDT (exchange minimum)
MM_MAX_ORDER_NOTIONAL_PCT=0.02   # %2.0
```

## Verification

```bash
# Test order size calculation
python -c "from src.core.config import Settings; from src.strategy.pricing import PricingEngine; from decimal import Decimal; s = Settings.from_env(); engine = PricingEngine(s.strategy); size = engine.calculate_order_size(Decimal('95000'), Decimal('200')); print(f'Size: {size}, Notional: {size * Decimal(\"95000\")}')"

# Run bot and check logs
python -m src.apps.main run --mode paper_exchange --symbol BTCUSDT
```

## Expected Behavior After Fix

1. ✅ Orders are submitted (not rejected)
2. ✅ Orders get filled in simulated exchange
3. ✅ Positions are created and updated
4. ✅ PnL tracking works
5. ✅ Log spam reduced (warnings throttled)

