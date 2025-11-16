# Geliştirme Yol Haritası

Bu doküman, market maker botunun geliştirme yol haritasını özetler.

## Fazlar

### ✅ FAZ 1: Proje Hazırlığı
- [x] Git repo + branch stratejisi (main, dev, feature/*)
- [x] Temel klasör yapısı
- [x] Teknoloji stack belirleme
- [x] Dokümantasyon yapısı

### ✅ FAZ 2: Strateji Tasarımı
- [x] Strateji tipi belirleme (V1 PMM, V2 AS)
- [x] Parametrelerin netleştirilmesi
- [x] Risk kuralları tanımlama
- [x] PnL & TCA çerçevesi

### ✅ FAZ 3: Sistem Mimarisi ve Temel Altyapı
- [x] High-level mimari diagram (ARCHITECTURE.md'de dokümante edildi)
- [x] Market data client (WebSocket) - `src/data/websocket.py`, `src/data/binance_public_client.py`
- [x] Execution client (REST/WebSocket) - `src/data/binance_client.py`, `IExchangeClient` interface
- [x] Konfigürasyon yönetimi - `src/core/config.py` (Pydantic Settings + .env)

### ✅ FAZ 4: Strateji Motoru (V1: Pure Market Making)
- [x] Temel quoting fonksiyonu - `src/strategy/pricing.py`
- [x] Basit inventory yönetimi - `src/strategy/inventory.py`
- [x] Quote lifecycle yönetimi - `src/strategy/market_maker.py`
- [x] Event-driven loop - `src/apps/paper_trading.py`, `src/strategy/market_maker.py`

### ✅ FAZ 5: Risk & Limit Katmanı
- [x] Pre-trade risk kontrolleri - `src/risk/guardian.py`, `src/risk/limits.py`
- [x] Pozisyon & zarar limitleri - `src/risk/limits.py`
- [x] Kill switch implementasyonu - `src/risk/guardian.py`
- [ ] Post-trade kontroller (kısmen - monitoring metrics var, detaylı analiz eksik)

### ✅ FAZ 6: Simülasyon & Backtest Altyapısı
- [x] Basit L1 simülatörü - `src/execution/simulated_exchange.py` (Live Paper Exchange)
- [x] Event-driven backtest engine - `src/backtest/engine.py`
- [x] Gerçek veri ile backtest - `src/backtest/data_loader.py`
- [ ] Calibration & parameter sweep (manuel test senaryoları var, otomatik sweep eksik)

## Geliştirme Sırası (Modül Bazlı)

1. **Core** - Domain modelleri, config, constants
2. **Data** - Binance client + websocket + orderbook modeli
3. **Execution (skeleton)** - Interface'ler ve temel yapı
4. **Risk** - Limits, guardian, metrics
5. **Strategy** - Market maker, pricing, inventory
6. **Monitoring** - Log, metrics, alerting
7. **Backtest** - Simulation engine
8. **Apps** - CLI / runner scripts

## Detaylı Plan

Detaylı faz planları için [Development Phases](DEVELOPMENT_PHASES.md) dokümanına bakın.

