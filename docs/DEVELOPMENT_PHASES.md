# Geliştirme Fazları (FAZ 3-6)

Bu doküman, market maker botunun geliştirme fazlarını detaylandırır.

---

## FAZ 3 – Sistem Mimarisi ve Temel Altyapı

### 1. High-level Mimari Diagram

#### Modüller

- **`MarketDataService`** - WebSocket ile market data alımı
- **`OrderBook`** - L1–L2 snapshot yönetimi
- **`StrategyEngine`** - Market making stratejisi motoru
- **`RiskEngine`** - Pre-trade risk kontrolleri ve kill switch
- **`ExecutionEngine`** - Emir gönderme, iptal, routing
- **`StateStore`** - DB/Redis ile state yönetimi (pozisyon, PnL, açık emirler)
- **`MonitoringService`** - Log, metrics, alerting

#### Veri Akışı

```
Market Data (WebSocket)
  ↓
OrderBook (L1/L2 Snapshot)
  ↓
StrategyEngine (Quote Hesaplama)
  ↓
RiskEngine (Pre-trade Kontroller)
  ↓
ExecutionEngine (Emir Gönderme)
  ↓
Exchange (Binance API)
  ↓
Fills (WebSocket / REST)
  ↓
StateStore (Pozisyon, PnL Güncelleme)
  ↓
MonitoringService (Log, Metrics, Alerts)
```

### 2. Market Data Client

**WebSocket ile:**
- Ticker (fiyat güncellemeleri)
- L1 veya L2 order book (best bid/ask veya tam order book)

**Özellikler:**
- Heartbeat & reconnect mekanizması
- Connection state yönetimi
- Error handling ve retry logic

**Model:**
- `OrderBookSnapshot` modeli:
  - `best_bid`, `best_ask`
  - `mid_price`
  - `spread` (bps veya absolute)
  - `timestamp`
  - `symbol`

### 3. Execution Client

**REST veya Private WebSocket üzerinden:**

**Interface:**
- `IExchangeClient` (abstract base class) - `src/core/exchange.py`
  - Exchange-agnostic interface tanımı
  - Gerçek exchange ve simulated exchange için ortak API

**Implementasyonlar:**
- `BinanceClient` - Gerçek Binance Futures API client
- `BinancePublicClient` - Public API client (sadece market data, KYC gerektirmez)
- `SimulatedExchangeClient` - Paper trading için lokal simülasyon

**Fonksiyonlar:**
- `submit_order(order: Order)` → `Order`
- `cancel_order(order_id, symbol)` → `bool`
- `cancel_all_orders(symbol)` → `int`
- `get_open_orders(symbol)` → `List[Order]`
- `get_positions(symbol)` → `List[Position]`
- `get_trades(symbol, limit)` → `List[Trade]`

**Özellikler:**
- Rate limit handling (HTTP 429)
- Network timeout handling
- Error handling ve retry logic
- Order state synchronization
- Paper trading modu için lokal order matching

### 4. Konfigürasyon Yönetimi

**`.env` dosyası:**
- API key/secret
- Base URL (testnet/live)
- Testnet/live flag
- Risk parametreleri (daily_loss_limit, max_inventory_pct, vb.)
- Strategy parametreleri (spread_bps, order_size_pct, refresh_ms, vb.)

**Çevreye göre profiller:**
- `dev` - Development ortamı
- `staging` - Test ortamı
- `prod` - Production ortamı

**Pydantic Settings ile:**
- Type-safe config yükleme
- Validation
- Environment variable override

---

## FAZ 4 – Strateji Motoru (V1: Pure Market Making)

### 1. Temel Quoting Fonksiyonu

**Input:**
- `OrderBookSnapshot` - Güncel order book durumu
- `current_inventory` - Mevcut net pozisyon
- `volatility_estimate` - Volatilite tahmini (30 dk realized vol)
- `config` - Strateji parametreleri

**Output:**
- `Quote {bid_price, ask_price, bid_size, ask_size}`

**Kurallar:**
1. Spread'i bps → price cinsine çevir
   - `spread_price = mid_price * (spread_bps / 10000)`
2. Inventory'ye göre mid'i kaydır (inventory skew)
   - `skewed_mid = mid_price + (inventory_skew_strength * inventory * price_impact)`
3. Volatilite yükseldikçe spread'i genişlet
   - `adjusted_spread = base_spread * (1 + vol_spread_factor * (vol / normal_vol))`
4. Final quote:
   - `bid_price = skewed_mid - (adjusted_spread / 2)`
   - `ask_price = skewed_mid + (adjusted_spread / 2)`

### 2. Basit Inventory Yönetimi

**Inventory Bandı:**
- `target_inventory = 0` (delta-nötr hedef)
- `inventory_soft_band = ±20%` bot sermayesi
- `inventory_hard_limit = ±30%` bot sermayesi

**Davranış:**
- Inventory bandının dışına çıktığında:
  - Spread'i agresif şekilde skew et
  - Gerekirse tek taraflı quote'a düş (sadece inventory azaltan tarafı quote et)
- Hard limit aşıldığında:
  - Yeni emir açmayı durdur
  - Flatten moduna geç

### 3. Quote Lifecycle Yönetimi

**Yeni Quote Hesaplandığında:**
1. Eski emirleri kontrol et:
   - Fiyat değiştiyse → cancel + yeni emir gönder
   - Fiyat aynıysa → mevcut emirleri koru
2. Yeni bid/ask emirlerini gönder:
   - `place_limit_order(bid_price, bid_size, "BUY")`
   - `place_limit_order(ask_price, ask_size, "SELL")`
3. Exchange tarafında "open order" durumu ile local state'i sync et:
   - Order ID, quantity, status takibi

### 4. Event-driven Loop

**`on_order_book_update` event'inde:**
```
OrderBook Update
  ↓
StrategyEngine.compute_quotes()
  ↓
RiskEngine.check_order_limits()
  ↓
ExecutionEngine.submit_orders()
```

**`on_fill` event'inde:**
```
Fill Event
  ↓
StateStore.update_inventory()
  ↓
StateStore.update_pnl()
  ↓
MonitoringService.log_trade()
```

---

## FAZ 5 – Risk & Limit Katmanı (Kill Switch Dahil)

Bu faz "sorunsuz çalışan" kısmı için kritik. Regülasyon dokümanları, otomatik sistemler için **pre-trade risk kontrolleri** ve **kill switch**'i "iyi uygulama" olarak tanımlıyor.

### 1. Pre-trade Risk Kontrolleri

#### Order Bazlı Kontroller

**Max Order Size:**
- `max_order_notional = bot_equity * order_notional_pct` (örn. 0.5-1%)
- `max_order_qty = max_order_notional / price`

**Fiyat Bandı:**
- Best bid/ask'ten belirli % kadar uzaklığa izin verme
- Örn. best bid'den %0.5'ten fazla aşağıda bid quote etme

#### Akış Bazlı Kontroller

**Rate Limits:**
- Saniye başına max emir sayısı: `max_new_orders_per_second = 5-10`
- Dakika başına max emir sayısı: `max_new_orders_per_minute = 300`
- Günlük toplam hacim/işlem sayısı limiti

**Cancel-to-Trade Ratio:**
- Uzun vadede `< 50:1` hedef
- Çok yüksek cancel oranı alarm tetikler

### 2. Pozisyon & Zarar Limitleri

#### Symbol Bazlı Limitler

**Max Pozisyon:**
- `max_net_notional_per_symbol = bot_equity * 0.3` (30%)
- `max_gross_notional_per_symbol = bot_equity * 0.6` (60%)

#### Portföy Bazlı Limitler

**Toplam Risk:**
- Tüm marketlerde net pozisyon: `max_total_net_notional = bot_equity * 0.5` (50%)

#### Günlük Max Zarar

**Realized PnL Limit:**
- `daily_loss_limit = bot_equity * 0.01` (1%)
- Altına indiğinde botu durdur

**Drawdown Limit:**
- Soft limit: `max_drawdown_soft = bot_equity * 0.10` (10%)
- Hard limit: `max_drawdown_hard = bot_equity * 0.15` (15%)

### 3. Kill Switch Implementasyonu

**Tek Fonksiyon:**
```python
def trigger_kill_switch(reason: str):
    # 1. Tüm açık emirleri iptal et
    cancel_all_orders()
    
    # 2. İstersen piyasa emriyle inventory'yi flatten et
    if config.flatten_on_kill_switch:
        flatten_inventory()
    
    # 3. Yeni emir açılmasını blokla (flag)
    set_trading_enabled(False)
    
    # 4. Alert gönder
    send_alert(f"Kill switch triggered: {reason}")
```

**Tetikleme Senaryoları:**
1. `daily_loss_limit` aşıldı
2. `max_drawdown_hard` aşıldı
3. `max_inventory_hard_limit` aşıldı
4. API hataları (sürekli 429/5xx) kritik eşik üzerinde
5. Monitoring servisi: anormal slippage, delayed fills

**Tetikleme Yöntemleri:**
- Sistem içinden (otomatik trigger)
- Manuel CLI/tuş ile

### 4. Post-trade Kontroller

**Periyodik Analiz:**
- Fills / PnL / inventory loglarının analizi
- Anormal pattern'ler için alarm eşikleri

**Alarm Eşikleri:**
- Çok düşük fill oranı (< %5)
- Aşırı cancel/trade oranı (> 50:1)
- Sürekli tek taraflı PnL kaybı
- Anormal slippage (> 3 ticks)

---

## FAZ 6 – Simülasyon & Backtest Altyapısı

Market maker'i OHLC bar ile test etmek yetmez; ideal olan, **order book ve emir akışı** ile simüle etmek. Akademik çalışmalar Avellaneda–Stoikov ve türev modelleri için genelde:
- Mid price için diffusion / random walk
- Müşteri emirleri için Poisson/Hawkes süreçleri kullanıyor

### 0. Live Paper Exchange (✅ Implemented)

**Mimari:**
- `BinancePublicClient` - Canlı market data (public API, KYC gerektirmez)
- `SimulatedExchangeClient` - Lokal order matching ve position tracking
- `paper_trading.py` - İki client'ı birleştiren orchestrator

**Özellikler:**
- Gerçek zamanlı order book verisi
- Lokal order matching (fill simulation)
- Position ve PnL tracking
- Risk kontrolleri ve kill switch çalışıyor
- Hiç gerçek para riski yok

**Kullanım:**
```bash
python -m src.apps.main run --mode paper_exchange --symbol BTCUSDT
```

### 1. Basit L1 Simülatörü

**Mid Price Simülasyonu:**
- Random walk mid price (Geometrik Brownian Motion)
- `dS = S * (μ * dt + σ * dW)`
- `S(t+1) = S(t) * exp((μ - σ²/2) * dt + σ * √dt * Z)`

**Order Book Simülasyonu:**
- `bid = mid - (spread / 2)`
- `ask = mid + (spread / 2)`
- Spread: sabit veya volatiliteye bağlı

**Fill Olasılığı:**
- Bot'un limit emirlerine Poisson süreci ile "fill olasılığı" ver
- Fiyatın ne kadar içerde olduğuna göre değişen rate:
  - `fill_rate = base_rate * exp(-distance_from_mid / spread)`

### 2. Event-driven Backtest Engine

**Zamanı Adım Adım İlerleten Döngü:**

```
1. Market State Update
   - Mid price update (random walk)
   - Order book update
   
2. Strategy → Quote
   - compute_quotes(order_book, inventory, vol)
   
3. Risk Check
   - check_order_limits(quote)
   - check_inventory_limits(inventory)
   - check_daily_loss(pnl)
   
4. Execution Sim
   - place_limit_order(quote)
   - update_open_orders()
   
5. Fill Sim
   - Poisson process ile fill olasılığı
   - Fill olduysa: update_inventory(), update_pnl()
   
6. State Update
   - update_timestamp()
   - log_state()
```

**Çıktılar:**
- PnL zaman serisi
- Inventory zaman serisi
- Fill oranı
- Max DD, Sharpe, spread PnL, commission cost, vb.

### 3. Gerçek Veri ile Backtest

**Tarihsel Data:**
- Seçilen borsa için tarihsel L1/L2 tick veya snapshot datası
- Binance için: aggTrades, order book snapshots

**Replay:**
- Bot'un davranışını bu data üzerinde replay et
- Gerçek market microstructure'ı simüle et
- DolphinDB'nin Avellaneda backtest tutorial'ı buna iyi örnek

### 4. Calibration & Parameter Sweep

**Grid Search / Random Search:**
- Spread (4-30 bps)
- Risk aversion (γ: 0.1-10)
- Refresh time (500-2000 ms)
- Inventory hedefi (0, ±10%, ±20%)
- Order size (0.5-3% bot equity)

**Her Parametre Seti İçin:**
- Backtest çalıştır
- Metrikleri kaydet:
  - Sharpe ratio
  - Max drawdown
  - Net PnL
  - Fill ratio
  - Cancel-to-trade ratio

**Optimizasyon:**
- En iyi parametre setini seç
- Overfitting'e dikkat et (out-of-sample test)

---

## Geliştirme Sırası Özeti

1. **FAZ 3** - Sistem mimarisi ve temel altyapı
   - Market data client
   - Execution client
   - Konfigürasyon yönetimi

2. **FAZ 4** - Strateji motoru (V1 PMM)
   - Quoting fonksiyonu
   - Inventory yönetimi
   - Quote lifecycle
   - Event-driven loop

3. **FAZ 5** - Risk & limit katmanı
   - Pre-trade kontroller
   - Pozisyon & zarar limitleri
   - Kill switch
   - Post-trade kontroller

4. **FAZ 6** - Simülasyon & backtest
   - L1 simülatörü
   - Event-driven backtest engine
   - Gerçek veri ile backtest
   - Parameter sweep

---

## Notlar

- Her faz, önceki fazların üzerine inşa edilir
- Test-driven development yaklaşımı önerilir
- Her faz sonunda integration test yapılmalı
- Monitoring ve logging her fazda entegre edilmeli

