# Risk Scaling Engine - ATR + Max Drawdown Based

## Genel Bakış

Market Maker botuna entegre edilmiş **ATR (Average True Range) + Max Drawdown** bazlı risk scaling engine, botun trading davranışını piyasa koşullarına ve performansına göre dinamik olarak ayarlar.

## Mimari

```
Market Data (Price, High/Low, Best Bid/Ask)
        ↓
Risk Scaling Engine
  ├─ ATR Calculation (EMA-based)
  ├─ Max Drawdown Calculation
  └─ Risk Multiplier Computation
        ↓
Market Maker
  ├─ Order Size Scaling (base_notional * risk_multiplier)
  ├─ Spread Scaling (widen when risk is low)
  └─ Quote Frequency Scaling (less frequent when risk is low)
        ↓
Exchange API (Orders)
```

## Risk Multiplier Hesaplama

### 1. ATR (Average True Range) Hesaplama

- **Period**: 14 (varsayılan, config'de ayarlanabilir)
- **Method**: EMA (Exponential Moving Average) - TradingView uyumlu
- **Input**: High, Low, Close fiyatları (orderbook'dan)
- **Output**: ATR değeri (volatilite ölçüsü)

```python
# True Range = max(high - low, abs(high - prev_close), abs(low - prev_close))
# ATR = EMA(True Range, period=14)
```

### 2. Volatilite Multiplier

ATR'a göre risk multiplier:

- **ATR < vol_low (0.5%)**: `multiplier = 1.5` (düşük volatilite → agresif)
- **ATR > vol_high (2.0%)**: `multiplier = 0.5` (yüksek volatilite → defansif)
- **Aralık**: Lineer interpolasyon (1.5 → 0.5)

### 3. Max Drawdown Hesaplama

- **Lookback Window**: 240 saat (10 gün, varsayılan)
- **Method**: Peak-to-trough drawdown
- **Input**: Equity serisi (wallet balance + unrealized PnL)
- **Output**: Max drawdown yüzdesi (örn: 0.12 = %12)

```python
# Peak equity'den başla
# Her equity değeri için: DD = (peak - equity) / peak
# Max DD'yi döndür
```

### 4. Drawdown Multiplier

DD'ye göre risk multiplier:

- **DD ≤ dd_soft (5%)**: `multiplier = 1.0` (normal)
- **DD ≥ dd_hard (15%)**: `multiplier = 0.1` (neredeyse dur)
- **Aralık**: Lineer interpolasyon (1.0 → 0.1)

### 5. Final Risk Multiplier

```python
risk_multiplier = vol_multiplier * dd_multiplier
risk_multiplier = clamp(risk_multiplier, risk_min=0.1, risk_max=2.0)
```

## Market Maker Entegrasyonu

### 1. Order Size Scaling

**Base Notional**: `base_notional_per_side` (varsayılan: 10 USDT)

```python
base_size = base_notional_per_side / mid_price
final_size = base_size * risk_multiplier
```

**Örnek**:
- `base_notional_per_side = 10 USDT`
- `mid_price = 100,000 USDT` (BTCUSDT)
- `risk_multiplier = 0.5` (yüksek risk)
- `base_size = 10 / 100,000 = 0.0001 BTC`
- `final_size = 0.0001 * 0.5 = 0.00005 BTC`

### 2. Spread Scaling

Risk düşükken spread genişler:

```python
spread_multiplier = 1.0 + (1.0 - risk_multiplier)
# risk_mult = 1.0 → spread_mult = 1.0 (normal)
# risk_mult = 0.1 → spread_mult = 1.9 (geniş)
```

**Örnek**:
- `base_spread = 8 bps`
- `risk_multiplier = 0.3`
- `spread_multiplier = 1.7`
- `final_spread = 8 * 1.7 = 13.6 bps`

### 3. Quote Frequency Scaling

Risk düşükken daha az sıklıkta quote:

```python
frequency_multiplier = 1.0 + (1.0 - risk_multiplier) * 2.0
refresh_interval = base_interval * frequency_multiplier
```

**Örnek**:
- `base_interval = 1.0 saniye`
- `risk_multiplier = 0.2`
- `frequency_multiplier = 2.6`
- `final_interval = 1.0 * 2.6 = 2.6 saniye`

### 4. Risk-Off Mode

`risk_multiplier < risk_off_threshold (0.3)` olduğunda:

- **Yeni pozisyon açılmaz**
- **Sadece mevcut pozisyonlar azaltılır**
- **Fiyatlar daha agresif** (fill garantisi için)

**Davranış**:
- Long pozisyon varsa → Sadece ASK quote (satış)
- Short pozisyon varsa → Sadece BID quote (alış)
- Flat pozisyon → Quote yok

## Konfigürasyon

`src/core/config.py` içinde `RiskConfig`:

```python
# Risk scaling parameters
enable_risk_scaling: bool = True
risk_scaling_atr_length: int = 14
risk_scaling_dd_lookback_hours: int = 240
risk_scaling_vol_low: float = 0.5  # ATR % threshold
risk_scaling_vol_high: float = 2.0  # ATR % threshold
risk_scaling_dd_soft: float = 0.05  # 5% DD
risk_scaling_dd_hard: float = 0.15  # 15% DD
risk_scaling_min: float = 0.1
risk_scaling_max: float = 2.0
risk_off_threshold: float = 0.3
base_notional_per_side: float = 10.0  # USDT
```

## Veri Akışı

### Her Quote Update'te:

1. **Price Update**: Orderbook'dan high/low/close alınır
2. **Equity Update**: Wallet balance + unrealized PnL hesaplanır
3. **Risk Multiplier**: ATR + DD'den hesaplanır
4. **Quote Generation**: Risk multiplier ile scale edilir
5. **Order Submission**: Risk-off modu kontrol edilir

### Her WebSocket Message'da:

1. Orderbook güncellenir
2. Market Maker'a bildirilir
3. Risk engine price serisini günceller
4. Risk multiplier yeniden hesaplanır

## Logging

Risk scaling engine her 50 quote update'te bir log yazar:

```
Risk scaling for BTCUSDT: multiplier=0.750, spread_mult=1.250, risk_off=False
```

Risk-off moduna geçildiğinde:

```
Risk-off mode: only quoting ask to reduce long position (qty=0.001, price=100500.00)
```

## Örnek Senaryolar

### Senaryo 1: Normal Piyasa (risk_mult = 1.0)

- ATR: Orta seviye
- DD: %2
- **Sonuç**: Normal order size, normal spread, normal frequency

### Senaryo 2: Yüksek Volatilite (risk_mult = 0.5)

- ATR: Yüksek (>2%)
- DD: %3
- **Sonuç**: 
  - Order size: %50 azalır
  - Spread: %50 genişler
  - Frequency: 2x yavaşlar

### Senaryo 3: Yüksek Drawdown (risk_mult = 0.2)

- ATR: Normal
- DD: %12 (soft-hard arası)
- **Sonuç**:
  - Order size: %80 azalır
  - Spread: %80 genişler
  - Frequency: 2.6x yavaşlar
  - Risk-off mode: Aktif (sadece pozisyon azaltma)

### Senaryo 4: Çok Yüksek Drawdown (risk_mult = 0.1)

- ATR: Normal
- DD: %18 (>hard threshold)
- **Sonuç**:
  - Order size: %90 azalır
  - Spread: %90 genişler
  - Frequency: 2.8x yavaşlar
  - Risk-off mode: Aktif

## Performans Etkisi

- **Dashboard**: Risk scaling engine dashboard update'lerini etkilemez (timeout koruması var)
- **Trading**: Risk scaling hesaplamaları çok hızlı (<1ms)
- **Memory**: Price ve equity serileri sınırlı (deque with maxlen)

## Test Etme

1. **Paper Trading**: `python -m src.apps.main run --mode paper_exchange --enable-dashboard`
2. **Dashboard'da**: Risk scaling metriklerini izleyin
3. **Log'larda**: Risk multiplier değişimlerini takip edin
4. **Manuel Test**: Yüksek volatilite veya drawdown simüle edin

## Gelecek İyileştirmeler

- [ ] Trend filtresi (EMA cross, ADX)
- [ ] Rejim filtresi (risk-on/off detection)
- [ ] Per-symbol risk scaling
- [ ] Machine learning based risk prediction

