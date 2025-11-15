# Market Maker Bot - Specification & Strategy Framework

## 1. Hedef Metrikler

### 1.1 Performans Metrikleri

#### Net Günlük Getiri (Rᵈ)
- **Hedef**: +0.05% – +0.20% / gün (bot sermayesi üzerinden)
- **Risk Trigger**: Üst üste 5 gün negatifse strateji parametrelerini gözden geçir

#### Sharpe Oranı (90 günlük)
- **Hedef**: Yıllıklandırılmış Sharpe ≥ 1.0–1.5
- **Alarm**: Sharpe 0.5 altına 2–3 ay üst üste düşerse stratejiyi "re-design" moduna al
- **Referans**:
  - < 1 → zayıf / yetersiz risk-getiri
  - 1 – 2 → kabul edilebilir / iyi
  - ≥ 2 → çok iyi / agresif

#### Maksimum Drawdown (MDD)
- **Soft Limit (Uyarı)**: Bot sermayesinde %10 MDD
- **Hard Limit (Kill-switch)**: %15 MDD → Botu otomatik durdur, parametreleri yeniden kalibre etmeden açma

#### Maksimum Günlük Zarar (Daily Max Loss)
- **Limit**: Bot sermayesinin %1'i
- **Aksiyon**: Günlük zarar %1'e ulaşırsa:
  - O gün stratejiyi kapat
  - Parametreleri değiştirmeden yeniden açma

#### Spread PnL (Brüt ve Net)
- **Brüt Spread PnL**: Alış ve satış fiyatı arasındaki spread'den kazanılan toplam PnL (fee hariç)
- **Net Spread PnL**: Brüt spread PnL – (komisyon + slippage)
- **Hedef**: Net spread PnL / toplam işlem hacmi günlük ortalama +1–3 bp (0.01–0.03%) pozitif
- **Alarm**: 30 günlük ortalama 0 veya negatif ise strateji ayarlama şart

#### Envanter (Inventory) ve Pozisyon Riski
- **Metrikler**:
  - Her market için net pozisyon (BTC/ETH miktarı)
  - Envanter volatilitesi (σ_inventory)
  - Toplam delta riski
- **Hedef**: Net BTC/ETH pozisyonu, bot sermayesinin %10'unu aşmasın
- **Örnek**: 1.000 USDT bot sermayesinde, BTCUSDT için net BTC pozisyonu ~100 USDT değerini aşmasın

## 2. İşlem Frekansı

### 2.1 Quote Güncelleme Periyodu
- **Başlangıç**: 1 saniye
- **Sakin Mod**: 1–2 saniye
- **Tetikler**: En iyi bid/ask seviyesinde anlamlı değişim olduğunda (örn. fiyat %0.02'den fazla oynadığında) anında re-quote

### 2.2 Hedef İşlem Yoğunluğu (Tek Parite)
- **Günlük Trade Sayısı (Fill)**: 50 – 300 arası (piyasa volatilitesine bağlı)
- **Günlük Gönderilen Order Sayısı**: 2.000–5.000 (iptal dahil)

### 2.3 Notlar
- Low / mid-frequency MM tasarımı (HFT değil)
- Yüksek likiditeli coinlerde daha dar spread ve daha sık refresh
- Düşük likiditede spread genişletilip refresh yavaşlatılmalı

## 3. Sermaye Planı

### 3.1 Katmanlar (Örnek: 1.000 USDT Toplam Sermaye)

#### Toplam Trading Sermayesi (Portfolio Level)
- **Örnek**: 1.000 USDT

#### Bot'a Ayrılan Pay (Strategy Level)
- **Öneri**: Toplam sermayenin maks. %20'si → 200 USDT
- **Geri kalan %80**: Kenarda veya daha düşük riskli varlıklarda

#### Borsa Bazında Limit (Exchange Level)
- **V1**: Tek borsa (Binance) → Bot sermayesinin tamamı (200 USDT) o borsadaki risk limiti

#### Market Bazında Limit (Symbol Level)
- **Her market için**: Bot sermayesinin maks. %30'u notional risk limiti
  - Örn. 200 USDT bot sermayesi → BTCUSDT için maks. 60 USDT net pozisyon
  - ETHUSDT için benzer
- **Toplamda**: Tüm marketlerde net pozisyon bot sermayesinin %50'sini geçmesin

#### Order Bazında Limit (Order Level)
- **Tek pasif emir büyüklüğü**: Bot sermayesinin %0.5 – 1'i
  - Örn. 200 USDT → order başına 1–2 USDT eşdeğeri
- **Aynı anda açık seviye**: 10–20 seviye olabilir, ama toplam açık risk market limitlerine bağlı kalmalı

### 3.2 Risk Kuralları (Formülize)

```python
# Günlük zarar limiti
daily_loss_limit = 0.01 * bot_equity  # Örn. 200 USDT → 2 USDT

# Max net pozisyon (her market için)
max_net_notional_per_symbol = 0.3 * bot_equity  # Örn. 200 USDT → 60 USDT

# Tek order notional
order_notional = 0.005 – 0.01 * bot_equity  # Örn. 200 USDT → 1-2 USDT
```

## 4. Pazar ve Borsa Seçimi

### 4.1 Borsa Seçimi

#### V1 Kararı: Binance Futures (USDT-Margin)
**Sebep**:
- En yüksek likidite
- Çok dar spread (özellikle BTCUSDT / ETHUSDT)
- Güçlü API dokümantasyonu ve public data kaynağı

**Fee Yapısı**:
- Spot: Normal kullanıcılar için maker/taker ~%0.1'den başlıyor
- Futures: Non-VIP için maker ~%0.02, taker ~%0.05

**İkincil (İleride)**: Bybit veya OKX (cross-exchange fırsatları / çoklu market testleri için)

### 4.2 Market Seçimi

#### V1 Pariteler: BTCUSDT ve ETHUSDT (Spot + Perp)

**BTC/USDT – Binance Spot**:
- 24h hacim: ~1.98 milyar USDT, ~20.7k BTC
- Son derece derin order book, düşük slippage

**ETH/USDT – Binance Spot**:
- 24h hacim: ~2.02 milyar USDT, ~640k ETH
- En yüksek hacimli paritelerden biri

**Binance Futures – BTCUSDT / ETHUSDT Perps**:
- 24h hacim: ~49–85 milyar $ aralığında
- Ortalama bid-ask spread: ~0.058% (5.8 bp), büyük paritelerde daha dar

### 4.3 Spread Genişliği

**Binance BTC/USDT**:
- En iyi bid/ask arasındaki fark: Çoğu zaman 0.01 USDT seviyesine kadar düşüyor
- ~95.000 USDT civarı BTC fiyatında: 0.00001–0.0001% ultra dar spread

**V1 Stratejisi**:
- **Başlangıç**: Hedef tam spread ~0.06–0.10% (her tarafa 0.03–0.05%)
- Backtest/paper-trade sonuçlarına göre yavaşça sıkılaştırılacak

### 4.4 Volatilite Resmi (30–90 Günlük)

**Bitcoin**:
- Son 12 ayda 30 günlük yıllıklandırılmış volatilite: ~%30–45
- 1 yıllık realized volatilite: ~%50+
- Günlük bazda tipik oynaklık: %2–3

**Strateji**:
- Volatilite yükseldiğinde:
  - Spread'i dinamik olarak genişletmek
  - Quote refresh hızını kısmak (örn. 1 saniyeden 2–3 saniyeye)

## 5. Özet: Bot Çerçevesi

### Hedefler
- ✅ Günlük getiri: Bot sermayesinin +0.05–0.20%
- ✅ 90 günlük Sharpe: ≥ 1–1.5
- ✅ Maksimum drawdown: Soft %10, Hard %15
- ✅ Maksimum günlük zarar: %1 (hit olursa bot kapanır)
- ✅ Net spread PnL / hacim: Pozitif, ideal olarak +1–3 bp
- ✅ Envanter: Tek markette net pozisyon bot sermayesinin %10'u, tüm marketlerde net pozisyon %50'yi aşmasın

### İşlem Frekansı
- ✅ Quote refresh: 1 saniye (volatil dönemde 0.5–1, sakin dönemde 1–2)
- ✅ Günlük hedef fill sayısı: 50–300 (tek parite)

### Sermaye Tahsisi (Örnek 1.000 USDT)
- ✅ Bot'a ayrılan pay: %20 → 200 USDT
- ✅ Her market için net pozisyon limiti: Bot sermayesinin %30'u
- ✅ Tek order notional: Bot sermayesinin %0.5–1'i

### Borsa + Market Seçimi
- ✅ Ana borsa: Binance Futures (USDT-M)
- ✅ Ana pariteler: BTCUSDT ve ETHUSDT (spot + perp)
- ✅ Çok yüksek hacim, dar spread, güçlü veri ekosistemi → V1 için ideal playground

## 6. Önemli Notlar

⚠️ **Risk Uyarısı**: Bu çerçeve eğitim ve simülasyon amacıyla hazırlanmıştır. Gerçek paraya geçerken mutlaka kendi risk toleransına ve hukuki durumuna göre yeniden gözden geçirilmelidir.

⚠️ **Türkiye Regülasyonu**: Türkiye'deki regülasyon, vergi ve KYC konularını ayrıca kontrol etmek önemlidir.

