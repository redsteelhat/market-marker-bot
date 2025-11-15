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

### 🔄 FAZ 3: Sistem Mimarisi ve Temel Altyapı
- [ ] High-level mimari diagram
- [ ] Market data client (WebSocket)
- [ ] Execution client (REST/WebSocket)
- [ ] Konfigürasyon yönetimi

### 📋 FAZ 4: Strateji Motoru (V1: Pure Market Making)
- [ ] Temel quoting fonksiyonu
- [ ] Basit inventory yönetimi
- [ ] Quote lifecycle yönetimi
- [ ] Event-driven loop

### 📋 FAZ 5: Risk & Limit Katmanı
- [ ] Pre-trade risk kontrolleri
- [ ] Pozisyon & zarar limitleri
- [ ] Kill switch implementasyonu
- [ ] Post-trade kontroller

### 📋 FAZ 6: Simülasyon & Backtest Altyapısı
- [ ] Basit L1 simülatörü
- [ ] Event-driven backtest engine
- [ ] Gerçek veri ile backtest
- [ ] Calibration & parameter sweep

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

