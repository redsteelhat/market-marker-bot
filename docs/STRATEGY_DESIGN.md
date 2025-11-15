# FAZ 2 – Strateji Tasarımı

Bu doküman, market maker botu için strateji tasarım sözleşmesini tanımlar. Kod değil, tamamen tasarım seviyesinde bir çerçevedir.

---

## 1. Strateji Tipi

### 1.1. V1 – Pure Market Making (PMM)

**Tanım:**
- Mid price (m) etrafında sürekli **bid** ve **ask** kotasyonu veren
- Temel geliri **bid–ask spread'i toplamak** olan
- Fiyat riskini, envanter (inventory) ve spread ayarlamalarıyla yöneten bir strateji

**Model Varsayımları:**
- Emirlerimiz limit order; fill olursa spread kazanıyoruz, fill olmazsa re-quote ediyoruz
- Mid price kısa vadede "noise + trend" ile hareket ediyor; biz "çok kısa horizonlı" risk alıyoruz
- Inventory büyüdükçe:
  - Spread'i o yöne doğru genişletiyoruz (daha pahalı sat, daha ucuz al)
  - Gerekirse tek taraflı quote moduna düşüyoruz (sadece inventory boşaltan tarafı quote etmek)

**V1 Hedefi:**
- Basit, anlaşılır ve **stabil** çalışan bir MM çekirdeği
- Parametreler doğrudan bot konfigürasyonuna gömülecek:
  - Spread, order size, inventory bandı, refresh frekansı, vb.

---

### 1.2. V2 – Avellaneda–Stoikov (AS) Market Making

Akademide ve pratikte "optimal market making" dendiğinde referans model: **Avellaneda–Stoikov**.

**Ana Fikir:**
- Mid price rastgele yürüyüş (Brownian / jump diffusion)
- Müşteri emirleri, kotasyonlarımızın mid'den uzaklığına bağlı **Poisson süreçleri** ile geliyor
- Parametreler:
  - `σ` (volatilite)
  - `γ` (risk aversion – risk iştahı)
  - `k` vs. (order arrival hızı)
  - `T` (horizon; hisse senetlerinde gün sonu, kriptoda genelde "sonsuz horizon" yaklaşımı)

**Model Çıktısı:**
- **Rezervasyon fiyatı** (inventory'e göre mid'i kaydırılmış fiyat)
- **Optimal half-spread** (risk/ödül dengesine göre hesaplanan yarım spread)

> `bid = rez_price – half_spread`, `ask = rez_price + half_spread`

**V2 Planı:**
- V1 PMM sorunsuz çalıştıktan sonra:
  - `compute_quotes()` fonksiyonunu AS formülasyonu ile yeniden parametrize edeceğiz
  - Volatilite ve fill oranına göre `γ`, `σ`, `k` gibi parametreleri kalibre edeceğiz

Bu doküman, **V1 PMM için parametreleri kesinleştiriyor**, V2 için "uyumlu" alanlar bırakıyor.

---

## 2. Temel Parametreler

### 2.1. Spread Parametreleri

Spread'i **basis point** (bps) cinsinden tanımlıyoruz. 1 bp = 0.01%.

Binance USDT-M futures tarafında **maker fee ~0.02%, taker fee ~0.05%** seviyesinden başlıyor.

#### Parametre Seti

**`base_spread_bps`** (full spread, iki taraf toplam)
- **Tanım**: Orta volatil koşullarda mid etrafında hedeflediğimiz **toplam spread**
- **Önerilen başlangıç**:
  - BTCUSDT, ETHUSDT için: **6 – 10 bps** (0.06 – 0.10% arası full spread)
  - Yani her tarafa 3–5 bps
- **Gerekçe**: Binance'de BTCUSDT perp'te efektif bid–ask spread çoğu zaman birkaç bps seviyesinde. Biz, çok yüksek hız ve kuyruk avantajımız olmadığı için biraz daha dışarıda quote ederek, daha geniş marjla ama daha az fill ile başlıyoruz

**`min_spread_bps`**
- **Tanım**: Vol düşükken dahi asla altına inmeyeceğimiz spread
- **Öneri**: **4 bps** (0.04%)
- **Gerekçe**: Maker fee ~2 bps; 4 bps altında agresifleştirmek, net PnL'i çok kolay negatife çevirebilir

**`max_spread_bps`**
- **Tanım**: Aşırı volatilite / stres durumunda çıkabileceğimiz maksimum spread
- **Öneri**: **30 bps** (0.30%)
- **Gerekçe**: Gün içi yüksek oynaklıkta (BTC'de günlük %2–3 hareketler normal) fiyat riski çok artıyor; AS ve türevi modeller yüksek volatilitede spread'i anlamlı şekilde genişletmeyi öneriyor

**`vol_spread_factor`**
- **Tanım**: Gerçekleşmiş / implied volatiliteye göre spread'i artıran katsayı
- **Örnek**: 30 dakikalık realized volatilite 1σ normal seviyeyi aştığında, spreade +2–4 bps ekle
- **Gerekçe**: AS modelinde spread, volatilite (σ) ile orantılı; yüksek σ → daha geniş spread

**`inventory_skew_strength`**
- **Tanım**: Inventory pozisyonuna göre mid'i kaydırma gücü
- **Öneri**: Başlangıç: **1.0 – 1.5**
- **Etki**: Inventory bandının uçlarına yaklaştıkça bid'i daha aşağı, ask'i daha yukarı taşıyarak inventory'yi azaltmaya zorluyor

---

### 2.2. Order Boyutu Parametreleri

Order boyutları, **bot sermayesi ve market volatilitesi** ile ilişkili olacak.

Binance Futures için komisyon formülü: `commission = notional * fee_rate` (fee_rate: maker 0.02%, taker 0.05% örneği).

#### Parametreler

**`order_notional_pct`**
- **Tanım**: Tek limit emir için kullanılacak notional, bot sermayesinin yüzdesi
- **Öneri**: Başlangıç: **0.5% – 1.0%**
  - Örnek: Bot sermayesi 200 USDT ise order başına 1–2 USDT notional
- **Amaç**: Yeterli fill alınırken, tek trade başına risk minimal tutulur

**`min_order_notional`**
- **Tanım**: Borsanın izin verdiği minimum notional + biraz üstü
- **Örnek**: Binance BTCUSDT perp için min order notional genelde birkaç USDT civarındadır; biz **>=10 USDT** gibi bir floor koyabiliriz (gerçek min'in üzerine çıkmak latency/fee etkisini daha anlamlı yapar)

**`max_order_notional`**
- **Tanım**: Tek emirle alınabilecek maksimum risk
- **Öneri**: **2 – 3%** bot sermayesi (örneğin 200 USDT'de 4–6 USDT)

**`dynamic_size_by_vol`**
- **Tanım**: Volatilite yükseldikçe order boyutunu azaltan mekanizma
- **Basit kural**:
  - σ düşük → `order_notional_pct` üst banda yakın
  - σ yüksek → alt banda çek

---

### 2.3. Quote Yenileme Frekansı

High-frequency literatüründe, market maker backtest'lerinde tipik "refresh interval" ms–saniye aralığında seçiliyor.

#### Parametreler

**`refresh_interval_ms`**
- **Tanım**: Periodik quote hesaplama ve update periyodu
- **Öneri**:
  - Başlangıç: **1000 ms (1 sn)**
  - Minimum: 500 ms (CPU ve rate limit'e göre)
  - Maksimum: 2000 ms (2 sn; çok yavaş olursa fırsat kaçabilir)

**`max_quote_age_ms`**
- **Tanım**: Bir quote'un "en fazla şu kadar süre" order book'ta kalmasına izin verilir; sonra zorunlu re-quote
- **Öneri**: = `refresh_interval_ms` * 2 (örn. 2 sn)

**`price_change_trigger_bps`**
- **Tanım**: Mid price belirli bir eşiğin üzerinde değiştiğinde anında re-quote tetikleyicisi
- **Öneri**: **5 bps** (0.05%) üzeri price shift → "immediate re-quote"

---

### 2.4. Hedef Inventory (Envanter) Bandı

Market-maker literatürü, **envanter riskini** en önemli risklerden biri olarak görüyor; AS ve benzeri modeller inventory'yi açıkça optimize ediyor.

#### Parametreler

**`target_inventory`**
- **Tanım**: Hedef net pozisyon (genelde 0)
- **Bizim seçimi**: **0** (delta-nötr hedef; directional risk almak istemiyoruz)

**`max_inventory_notional_pct_per_symbol``**
- **Tanım**: Her market için izin verilen maksimum net pozisyon (USDT cinsinden), bot sermayesine göre
- **Öneri**: **30%** (örn. 200 USDT bot sermayesinde, BTCUSDT için net pozisyon değeri max 60 USDT)
- Bu aynı zamanda **Risk parametreleri** altında da tekrarlanacak

**`inventory_soft_band`**
- **Tanım**: Inventory bu bandın dışına çıktığında spreadler agresif şekilde skew edilir, ama bot durmaz
- **Öneri**: ±**20%** bot sermayesi

**`inventory_hard_limit`**
- **Tanım**: Inventory bu limiti aşarsa bot, yeni emir açmayı durdurur ve flatten moduna geçer
- **Öneri**: ±**30%** bot sermayesi

**`inventory_skew_function`**
- **Tanım**: Inventory / limit oranına göre spread kaydırma fonksiyonu
- **Öneri**: lineer veya hafif konveks:
  - `skew ∝ (inventory / inventory_hard_limit) * inventory_skew_strength`

---

### 2.5. İşlem Ufku (Horizon) ve Flatten Politikası

Klasik Avellaneda–Stoikov hisse senetleri için "gün sonu (T)" ile yazılmıştı; gün sonunda inventory sıfırlanır varsayımı var.

Kripto tarafında:
- 7/24 açık piyasa
- Hummingbot ve yeni nesil modeller bu yüzden "sonsuz horizon" veya "uzun horizon" varsayımı kullanıyor

#### Bizim Yaklaşımımız

**`trading_horizon`**
- **Tanım**: Stratejinin planlanan çalışma süresi
- **Seçim**: Teknik olarak **sürekli (7/24)**, ama operasyonel olarak **günlük kapatma pencereleri** ile birlikte

**`daily_maintenance_window`**
- **Tanım**: Gün içinde botu manuel/otomatik durdurup, logları incelediğimiz ve gerekirse parametre güncellediğimiz pencere
- **Öneri**: Günde 1 kez, 10–30 dakikalık pencere (örneğin düşük hacimli bir saat diliminde)

**`flatten_on_shutdown`**
- **Tanım**: Bot planlı şekilde durdurulduğunda tüm inventory'nin kapatılması
- **Öneri**: Varsayılan: **Evet** → "bot kapanırken flatten et"
- **İstisna**: Çok illikit / açılması zor pozisyonlar varsa kademeli kapatma stratejisi

**`flatten_on_hard_risk_event`**
- **Tanım**: Günlük max zarar, MDD, inventory hard limit gibi risk event'lerinde otomatik flatten
- **Varsayılan**: **Evet** (Risk bölümünde detaylandırılacak "kill switch" ile birlikte)

---

## 3. Risk Parametreleri

Bu bölüm, stratejinin "kırmızı çizgilerini" tanımlar. Buradaki limitler, **pre-trade risk kontrolleri** ve **kill switch** mekanizmasında kullanılacaktır.

### 3.1. Maksimum Enstrüman Bazlı Pozisyon

**`max_net_notional_pct_per_symbol`**
- **Tanım**: Her bir sembol için izin verilen maksimum net pozisyon (USDT cinsinden)
- **Öneri**: **30%** bot sermayesi

**`max_gross_notional_pct_per_symbol`**
- **Tanım**: Long + short mutlak pozisyon toplamının limiti (hedged pozisyonlarda da kontrol)
- **Öneri**: **60%** bot sermayesi

---

### 3.2. Günlük Maksimum Zarar ve Drawdown

Risk yönetimi kaynakları, günlük zarar limitini genelde portföy sermayesinin **%1–2'si** civarında tutmayı öneriyor; bizim bot sermayemiz zaten portföyün alt kümesi olduğundan bu daha da kritik.

**`daily_loss_limit_pct`**
- **Tanım**: Bot sermayesi üzerinden günlük maksimum realized PnL kaybı
- **Öneri**: **1%** (örnek: 200 USDT → 2 USDT)
- **Davranış**: Realized PnL ≤ –1% → kill switch:
  - Tüm emirler iptal
  - Inventory flatten (mümkün olan en düşük market impact ile)
  - Gün sonuna kadar yeni emir yok

**`max_drawdown_pct`**
- **Tanım**: Bot için tolere edilecek maksimum equity düşüşü (running peak'ten)
- **Öneri**: Soft limit: **10%**, Hard limit: **15%**
- **Davranış**:
  - Soft limit aşıldığında: uyarı + parametreleri gözden geçirme
  - Hard limit aşıldığında: bot otomatik olarak kapanır, flatten moduna geçer

---

### 3.3. Emir Limitleri (Rate Limits & Flood Kontrolü)

Exchange rate limit + kendi risk yönetimimiz açısından önemli:

**`max_open_orders_per_symbol`**
- **Tanım**: Aynı anda order book'ta açık kalmasına izin verilen maksimum emir sayısı
- **Öneri**: V1'de: **2 – 4** (her tarafta 1–2 fiyat seviyesi)

**`max_new_orders_per_second`**
- **Tanım**: Saniye başına gönderilebilecek maksimum yeni emir sayısı
- **Öneri**: **5** (market başına) veya tüm bot için **10**
- **Davranış**: Limit aşılırsa throttle: yeni kotasyon bir sonraki cycle'a ötelenir

**`max_cancels_per_second`**
- **Tanım**: Saniye başına maksimum cancel sayısı
- **Öneri**: **5 – 10** (borsanın limitlerine göre ayarlanacak)

**`max_cancel_to_trade_ratio`**
- **Tanım**: Toplam cancel / toplam trade oranı için izleme metriği
- **Öneri**: Uzun vadede **< 50:1** hedef
- **Neden**: Çok yüksek cancel oranı, bazı borsalar tarafından cezalandırılabiliyor ve market microstructure literatüründe "spammy" davranış olarak kabul ediliyor

---

### 3.4. Kill Switch Senaryoları

Kill switch, aşağıdaki koşullardan herhangi biri tetiklenirse devreye giren **son savunma katmanı**:

1. `daily_loss_limit_pct` aşıldı
2. `max_drawdown_pct` hard limit aşıldı
3. `max_inventory_notional_pct_per_symbol` hard limit aşıldı
4. API hataları (ör. sürekli 429/5xx) belirli süre boyunca **kritik eşik** üzerinde
5. Monitoring servisi: anormal slippage, delayed fills, vs. (TCA kısmında tanımlanan threshold'lar)

**Davranış:**
- Tüm açık emirleri iptal et
- Inventory'yi kademeli veya doğrudan flatten et (config'e bağlı)
- Yeni emir açmayı engelle (manuel reset gerektir)

---

## 4. PnL ve Cost Modelleri

### 4.1. Maker / Taker Fee Modeli

**Binance USDT-M Futures (2025 itibarıyla):**
- Başlangıç taker fee: yaklaşık **0.05%** (5 bps)
- Başlangıç maker fee: yaklaşık **0.02%** (2 bps)
- BNB kullanımı ve VIP seviyesine göre daha da düşebiliyor

#### Parametreler

**`maker_fee_bps`**
- Varsayılan: **2 bps** (0.02%)

**`taker_fee_bps`**
- Varsayılan: **5 bps** (0.05%)

**`fee_discount_factor`**
- **Tanım**: BNB tutulması, VIP seviye, kampanyalar vs. nedeniyle efektif fee'yi düşürmek için çarpan
- **Örnek**: VIP1 + BNB → efektif maker fee ~1.6 bps ise, `fee_discount_factor ≈ 0.8`

**Komisyon Hesabı:**
- `commission = notional * fee_rate`
- PnL raporlamasında:
  - Spread PnL
  - Inventory PnL
  - Funding PnL (perp için)
  - **Commission cost** ayrı ayrı track edilecek

---

### 4.2. Slippage ve Spread Modeli

TCA literatüründe **slippage**, karar verdiğimiz referans fiyata göre gerçekleşen fill fiyatının farkı olarak tanımlanır.

Biz, iki tür slippage modelleyeceğiz:

1. **Maker slippage**
   - Fiyat hareket ederken, pasif limit emrimiz beklenenden daha az avantajlı seviyede fill olabilir (örneğin mid'i kaçıran fill'ler)
   - Genelde **0–1 tick** düzeyinde farz edilebilir

2. **Taker slippage**
   - Stop, acil flatten veya piyasa emirlerinde:
     - Karar anındaki "arrival price" ile gerçek fill fiyatı arasında fark
     - Order book derinliğine bağlı olarak birden fazla seviyeden fill olabilir

#### Parametreler

**`tick_size`**
- Borsanın kontrat bazlı tick size'ı (örn. BTCUSDT: 0.1 / 0.01 vs. borsanın belirlediği)

**`maker_slippage_ticks`**
- Varsayılan: **0 – 1 tick** (konservatif modellemede 0 alabiliriz)

**`taker_slippage_ticks`**
- Varsayılan: **1 – 3 tick** (market order / aggressive taker durumları için)

**Model:**
- Simülasyon ve backtest'te:
  - `effective_fill_price_maker = limit_price ± maker_slippage_ticks * tick_size`
  - `effective_fill_price_taker = best_quote ± taker_slippage_ticks * tick_size`

---

### 4.3. Transaction Cost Analysis (TCA) Metrikleri

Crypto TCA üzerine yazılan çalışmalar, özellikle şu metrikleri ön plana çıkarıyor: **slippage vs. VWAP/TWAP, arrival price, spread ve participation**, ayrıca cancel-to-trade oranları.

Strateji tasarımında izleyeceğimiz TCA metrikleri:

1. **Slippage vs Arrival Price**
   - `slippage_arrival = sign(side) * (fill_price – arrival_price)`
   - Arrival price: emir kararını verdiğimiz andaki mid veya best bid/ask
   - Amaç: Execution kalitemizi base-line'a göre ölçmek

2. **Slippage vs VWAP**
   - `slippage_vwap = sign(side) * (fill_price – VWAP_window)`
   - VWAP (Volume Weighted Average Price), belirli bir periyotta hacimle ağırlıklandırılmış fiyat
   - Makaleler, iyi execution'un genelde VWAP etrafında ± birkaç bps bandında kalması gerektiğini söylüyor

3. **Effective Spread ve Realized Spread**
   - Effective spread: `2 * sign(side) * (fill_price – mid_at_arrival)`
   - Realized spread: Belirli bir horizon sonra (örneğin 5 sn / 30 sn) mid'e göre tekrar hesaplanan spread
   - Amaç: Aldığımız spread'i gerçekten koruyor muyuz yoksa hemen mark-to-market kaybına mı dönüyor?

4. **Fill Ratio**
   - `fill_ratio = filled_qty / posted_qty`
   - Çok düşük fill ratio → spread çok geniş veya quote pozisyonu zayıf
   - Çok yüksek fill ratio → aşırı agresif spread, yüksek inventory riski

5. **Cancel-to-Trade Ratio**
   - `cancel_to_trade = total_cancels / total_fills`
   - Özellikle HFT ve MM tarafında önemli bir performans ve davranış metriği

6. **Short-Horizon Markout PnL**
   - `markout_pnl_5s`, `markout_pnl_30s`, `markout_pnl_300s`
   - Her fill için 5/30/300 sn sonra mid'e göre PnL hesabı
   - Amaç: Sistematik olarak "yanlış tarafta" mı kalıyoruz? (adverse selection analizi)

---

### 4.4. PnL Ayrıştırma

PnL'i, hem backtest hem canlı izleme için bileşenlerine ayıracağız:

1. **Spread PnL**
   - Alış ve satış arasındaki brüt fark (pre-cost):
     - `spread_pnl = Σ (sell_price – buy_price) * min(qty_buy, qty_sell)`
   - Hedef: Spread PnL uzun vadede **pozitif ve istikrarlı** olmalı

2. **Inventory PnL (Mark-to-Market)**
   - Fiyat hareketi nedeniyle net pozisyonumuz üzerinden oluşan PnL
   - Genelde daha volatil; riskin asıl kaynağı

3. **Commission Cost (Fees)**
   - Maker + taker komisyonları ayrı track edilecek:
     - `maker_commission = Σ (notional_maker * maker_fee_rate)`
     - `taker_commission = Σ (notional_taker * taker_fee_rate)`

4. **Slippage Cost**
   - `slippage_cost = Σ (sign(side) * (fill_price – decision_price) * qty)`

5. **Funding PnL (Perpetual kontrat ise)**
   - Funding ödemeleri/alacakları:
     - `funding_pnl = Σ (position_notional * funding_rate * funding_interval_factor)`

6. **Net PnL**
   - `net_pnl = spread_pnl + inventory_pnl + funding_pnl – commission_cost – slippage_cost`

Bu ayrıştırma, AS veya daha ileri MM modellerini kalibre ederken; özellikle hangi kısımda problem olduğunu (spread, inventory, cost) hızlıca teşhis edebilmemizi sağlayacak.

---

## Özet: Tasarım Çerçevesi

Bu dokümanla birlikte:
- ✅ Strateji tipi (V1 PMM, V2 AS)
- ✅ Spread, order boyutu, refresh, inventory, horizon parametreleri
- ✅ Risk limitleri
- ✅ PnL & TCA çerçevesi

tamamen netleştirilmiş durumda.

Bir sonraki fazda, bunları doğrudan yansıtacak şekilde:
- `config.yaml` / `config.json` şeması
- `StrategyConfig`, `RiskConfig`, `CostModelConfig` gibi Python tarafındaki yapıların iskeletini

tasarlayıp, kod mimarisine geçebiliriz.

