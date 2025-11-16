# Testing Guide

Bu doküman, market maker bot'un sistematik test ve kalibrasyon sürecini açıklar.

## Faz 1: Fonksiyonel Doğrulama Testleri

### 1.1 Tek Sembol, Düşük Frekans Testi

```bash
python -m src.apps.main run --mode paper_exchange --symbol BTCUSDT
```

**Beklenenler:**
- Order book her tick'te güncelleniyor
- Strategy → Risk → SimulatedExchange zinciri çalışıyor
- Açık emir sayısı limitleri aşılmıyor
- Kill switch tetiklenmiyor

**Kontrol:**
- Log'larda `submit_order`, `FILLED`, `Position updated` mesajları görülmeli
- `python -m src.apps.main status` ile runtime metrikleri kontrol edilmeli

### 1.2 Açık Emir Davranışı Testi

`.env` dosyasında:
```env
MM_BASE_SPREAD_BPS=2  # Çok dar spread
```

**Beklenenler:**
- Emirler hızlı doluyor
- Fill rate yüksek
- Inventory riski artıyor

### 1.3 Envanter Limit Testi

`.env` dosyasında:
```env
MM_MAX_INVENTORY_NOTIONAL_PCT_PER_SYMBOL=5  # Çok düşük (%5)
MM_HARD_INVENTORY_BAND_PCT=5
```

**Beklenenler:**
- Risk guardian "inventory limit aşıldı" mesajı veriyor
- Yeni emirler reddediliyor
- Log'larda `order rejected by guardian` görülüyor

### 1.4 Daily Loss Limit Testi

`.env` dosyasında:
```env
RISK_DAILY_LOSS_LIMIT_PCT=0.1  # %0.1 (çok düşük)
MM_BASE_SPREAD_BPS=1  # Çok dar spread (zarar edecek)
```

**Beklenenler:**
- Birkaç trade sonra kill switch tetikleniyor
- Strategy yeni emir üretmiyor
- Status komutunda kill switch durumu görülüyor

**Test Senaryoları:**
```bash
# Inventory limit testi
python scripts/test_scenarios.py inventory

# Kill switch testi
python scripts/test_scenarios.py killswitch

# Order limit testi
python scripts/test_scenarios.py orders
```

## Faz 2: Stabilite & Dayanıklılık Testleri

### 2.1 Uzun Süreli Koşu Testi

```bash
# En az 1-2 saat çalıştır
python -m src.apps.main run --mode paper_exchange --symbol BTCUSDT
```

**Kontrol Edilecekler:**
- Memory leak: RAM kullanımı artıyor mu?
- Trade history: Son 10k trade'den fazlası tutulmuyor
- WebSocket reconnect: Bağlantı kopunca otomatik reconnect çalışıyor mu?

### 2.2 WebSocket Reconnect Testi

1. Botu çalıştır
2. İnterneti 10-20 saniye kes
3. Bot otomatik reconnect yapmalı veya kontrollü exit etmeli

**Beklenenler:**
- Log'larda "WebSocket disconnected" ve "reconnecting" mesajları
- Panic crash olmamalı
- Reconnect sonrası normal çalışmaya devam etmeli

### 2.3 Exception Handling Testi

**Test Senaryoları:**
- REST timeout
- JSON parse hatası
- Symbol not found
- Invalid order data

**Beklenenler:**
- Uygulama sert crash olmamalı
- Log'larda WARNING/ERROR mesajları
- Retry mekanizması çalışmalı

## Faz 3: Strateji Kalibrasyonu

### 3.1 Spread Tuning

Paper trading'de birkaç saatlik koşudan sonra:

**Metrikler:**
- Toplam trade sayısı
- Toplam realized PnL
- Average spread PnL
- Net PnL (fee sonrası)

**Test Parametreleri:**
```env
# Dar spread
MM_BASE_SPREAD_BPS=4

# Geniş spread
MM_BASE_SPREAD_BPS=15
```

**Hedef:**
- Pozitif spread PnL
- Inventory ve drawdown kontrol altında

### 3.2 Inventory Band Tuning

```env
# Soft band
MM_SOFT_INVENTORY_BAND_PCT=15

# Hard band
MM_HARD_INVENTORY_BAND_PCT=25
```

**Beklenenler:**
- Soft band'de: Strategy quote'ları inventory'ye ters yönde bias'layıyor
- Hard band'de: Yeni pozisyon açmayı durduruyor, sadece inventory sıfırlamaya odaklanıyor

## Faz 4: Monitoring & Gözlemleme

### 4.1 Status Komutu

```bash
python -m src.apps.main status
```

**Gösterilen Metrikler:**
- Net PnL (realized + unrealized)
- Equity
- Open positions (symbol, qty, entry_price, current_price, PnL)
- Open orders per symbol
- Cancel/trade ratio
- Sharpe ratio (rolling, son 24 saat)
- Max drawdown (gün içi)
- Kill switch durumu

### 4.2 Runtime Status Updates

Paper trading modunda bot her 5 dakikada bir status update yazdırır:
- Equity
- PnL
- Trade count
- Sharpe ratio
- Kill switch durumu

## Faz 5: Backtest Modu

### 5.1 Historical Data Format

`data/backtest/` dizininde CSV dosyaları:

**Order Book CSV (`{SYMBOL}_orderbook.csv`):**
```csv
timestamp,bid_price,bid_size,ask_price,ask_size
2024-01-01T00:00:00,50000.00,0.1,50010.00,0.1
2024-01-01T00:00:01,50001.00,0.1,50011.00,0.1
```

**Trades CSV (`{SYMBOL}_trades.csv`):**
```csv
timestamp,price,quantity,side
2024-01-01T00:00:00,50005.00,0.001,BUY
```

### 5.2 Backtest Çalıştırma

```bash
python -m src.apps.main run --mode backtest --symbol BTCUSDT
```

**Sonuçlar:**
- PnL curve
- Trade listesi
- Risk metrikleri (Sharpe, MDD)
- Kill switch durumu

## Faz 6: Gerçek Exchange'e Geçiş (Binance TR)

### 6.1 Hazırlık

1. `BinanceTRClient` implementasyonu (ileride)
2. `.env` dosyasında:
   ```env
   TRADING_MODE=live
   BINANCE_TR_API_KEY=your_key
   BINANCE_TR_API_SECRET=your_secret
   ```

### 6.2 İlk Testler

**Çok Conservative Parametreler:**
```env
MM_ORDER_NOTIONAL_PCT=0.001  # Çok küçük order size
RISK_DAILY_LOSS_LIMIT_PCT=0.1  # %0.1
```

**Test Süresi:**
- İlk test: 1 saat
- İkinci test: 4 saat
- Üçüncü test: 1 gün

## Test Checklist

- [ ] Fonksiyonel testler (inventory, kill switch, order limits)
- [ ] Uzun süreli dayanıklılık testi (1-2 saat)
- [ ] WebSocket reconnect testi
- [ ] Exception handling testi
- [ ] Spread kalibrasyonu
- [ ] Inventory band kalibrasyonu
- [ ] Status komutu testi
- [ ] Backtest modu testi (historical data ile)
- [ ] Memory leak kontrolü
- [ ] Performance metrikleri toplama

## Önerilen Test Sırası

1. **Fonksiyonel Testler** (1-2 saat)
   - Inventory limit
   - Kill switch
   - Order limits

2. **Stabilite Testleri** (2-4 saat)
   - Uzun süreli koşu
   - WebSocket reconnect
   - Exception handling

3. **Kalibrasyon** (Birkaç gün)
   - Spread tuning
   - Inventory band tuning
   - Risk limit tuning

4. **Monitoring** (Sürekli)
   - Status komutu kullanımı
   - Metrik takibi
   - Log analizi

5. **Backtest** (İsteğe bağlı)
   - Historical data ile test
   - Parametre optimizasyonu

6. **Live Trading** (Hazır olduğunda)
   - Çok küçük boyutlarla başla
   - Aşamalı olarak artır

