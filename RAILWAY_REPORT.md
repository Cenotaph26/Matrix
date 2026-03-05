# NautilusTrader — Railway Uyumluluk & Güvenlik Raporu

## 1. Genel Değerlendirme

**Proje:** `nautilus_trader v1.225.0` (Nautech Systems)  
**Lisans:** LGPL-3.0-or-later  
**Dil:** Python 3.12+ / Cython / Rust (PyO3)

---

## 2. Railway'e Özgü Sorunlar ve Çözümler

### 🔴 KRİTİK: Rust + Cython Derleme Gereksinimi

**Sorun:** Proje 107 adet `.pyx` (Cython) dosyası ve Rust crate'leri içermektedir.
Standart `pip install` çalışmaz; derleme için şunlar gereklidir:
- `rustup` + Rust stable 1.93.1
- `clang` / `gcc`
- `capnproto` + `libcapnp-dev`
- `cython==3.2.4`
- `poetry-core==2.3.1`

**Çözüm:** Railway'de `DOCKERFILE` builder kullanılmalıdır (Nixpacks desteklemez).
`railway.toml` içinde `builder = "DOCKERFILE"` ayarlanmıştır.
`Dockerfile` iki aşamalı (multi-stage) build kullanır:
- Stage 1 (builder): Rust + Cython derleme ortamı
- Stage 2 (runtime): Sadece derlenmiş `.so` dosyaları + uygulama kodu

**Build süresi uyarısı:** İlk build ~20-40 dakika sürebilir.
Railway'in ücretsiz planında zaman aşımına uğrayabilir → Pro plan önerilir.

---

### 🟡 ORTA: `nixpacks.toml` yoktu

Railway varsayılan olarak Nixpacks kullanmaya çalışırdı ve Rust/Cython derleme
adımlarını atlardı. `railway.toml` dosyasına `builder = "DOCKERFILE"` eklendi.

---

### 🟡 ORTA: `PORT` ortam değişkeni

Railway her servise dinamik `PORT` atar. `main.py` bu değeri `os.environ["PORT"]`
üzerinden okur ve FastAPI health sunucusunu o portta başlatır.

---

## 3. Güvenlik Bulguları

### ✅ TEMİZ: Hardcoded credential yok

Tüm API key referansları `None` veya `os.environ.get(...)` şeklinde yazılmış.
Üretim değerleri Railway Variables paneline girilmelidir.

```
BINANCE_API_KEY     ← Railway Variables
BINANCE_API_SECRET  ← Railway Variables
```

### ✅ TEMİZ: Telemetri / phone-home yok

Kaynak kodda Mixpanel, Sentry, Datadog veya herhangi bir üçüncü taraf analitik
çağrısı bulunmamaktadır.

### ✅ TEMİZ: pickle kullanımı yok

`__reduce__` override veya `pickle.loads()` gibi deserializasyon riskleri yok.

### ⚠️ DİKKAT: `eval()` — `nautilus_trader/persistence/funcs.py:163`

```python
allowed_globals = {"field": field}
return eval(s, allowed_globals, {})  # noqa: S307
```

**Bağlam:** PyArrow filtre ifadelerini parse etmek için kullanılır.
**Risk seviyesi:** DÜŞÜK — girdi regex ile önceden doğrulanmaktadır;
yalnızca `field(name) op value` kalıbına izin verilir.
Kullanıcı girdisi doğrudan geçirilmiyorsa güvenlidir.
**Öneri:** Persistence/catalog özelliklerini kullanıyorsanız bu fonksiyona
iletilen string'leri kontrol edin.

### ⚠️ DİKKAT: Polymarket script'leri — özel anahtar işleme

```
nautilus_trader/adapters/polymarket/scripts/create_api_key.py
nautilus_trader/adapters/polymarket/scripts/set_allowances.py
```

Bu dosyalar `POLYMARKET_PK` (private key) ve `POLYGON_PRIVATE_KEY` ortam
değişkenlerini okuyarak blockchain işlemi gerçekleştirir.

**Risk seviyesi:** ORTA — bu script'ler yalnızca manuel çalıştırma için
tasarlanmıştır, bot tarafından otomatik olarak çağrılmazlar.
**Öneri:** Polymarket adaptörü kullanmıyorsanız bu dosyaları projenizde
bulundurmayın veya Docker imajından hariç tutun.

**Yapılan işlem:** `.dockerignore` ve Dockerfile Stage 2'de
`nautilus_trader/adapters/polymarket/scripts/` dizini kopyalanmamaktadır.

### ⚠️ DİKKAT: `ast.literal_eval` — Polymarket scripts

```
nautilus_trader/adapters/polymarket/scripts/active_markets.py:47
nautilus_trader/adapters/polymarket/scripts/list_updown_markets.py:102
```

`eval()` değil `ast.literal_eval()` kullanılmış — bu güvenlidir.
Sadece Python literal değerlerini (string, int, list vs.) değerlendirir,
kod çalıştırmaz.

### ✅ TEMİZ: `subprocess` — sadece build.py içinde

`subprocess.run()` çağrıları yalnızca `build.py` içindedir ve yalnızca
derleme sırasında (`cargo build`, `cython`) çalışır. Runtime'da çalışmaz.

---

## 4. Kaldırılan / İzole Edilen Bileşenler

Aşağıdaki klasörler Docker imajına **dahil edilmemiştir** (`.dockerignore`):

| Klasör | Neden |
|--------|-------|
| `tests/` | 87MB test verisi, üretimde gereksiz |
| `tests/test_data/` | 33MB binary test dosyaları |
| `docs/` | Dokümantasyon |
| `assets/` | Görseller |
| `scripts/ci/` | CI/CD pipeline script'leri |
| `.docker/` | Dev ortamı Docker config'i |

---

## 5. Önerilen Railway Variables

Railway → Service → Variables paneline ekleyin:

```
# Zorunlu
BINANCE_API_KEY=your_key_here
BINANCE_API_SECRET=your_secret_here

# Opsiyonel (varsayılanlar güvenli)
BINANCE_ACCOUNT_TYPE=USDT_FUTURES   # SPOT | USDT_FUTURES | COIN_FUTURES
BINANCE_ENV=DEMO                     # DEMO | TESTNET | LIVE
SYMBOL=BTCUSDT-PERP
TRADE_SIZE=0.001
TREND_PERIOD=5
BREAK_THRESHOLD_PCT=0.05
STOP_LOSS_PCT=0.5
LOG_LEVEL=INFO
TRADER_ID=TRENDBREAK-001
```

> ⚠️ `BINANCE_ENV=LIVE` olarak ayarlamadan önce DEMO/TESTNET'te kapsamlı
> test yapın. Gerçek para kaybı riski bulunur.

---

## 6. Deploy Adımları

```bash
# 1. Projeyi GitHub'a yükle
git init && git add . && git commit -m "nautilus railway deploy"
git remote add origin https://github.com/KULLANICI/trendbreak-nautilus.git
git push -u origin main

# 2. Railway'de:
#    New Project → Deploy from GitHub Repo → repo seç
#    Variables paneline yukarıdaki değerleri gir
#    Deploy otomatik başlar (Dockerfile kullanır)

# 3. İlk build ~20-40 dk sürer (Rust derleme)
#    Sonraki build'ler layer cache sayesinde ~5 dk
```

---

## 7. Proje Yapısı (Railway versiyonu)

```
nautilus-railway/
├── Dockerfile              ← Multi-stage build (Rust + Cython)
├── railway.toml            ← Railway config (DOCKERFILE builder)
├── .dockerignore           ← Test/doc/asset exclusions
├── main.py                 ← Entry point (TradingNode + health server)
├── requirements-runtime.txt← FastAPI + uvicorn
├── strategy/
│   └── trend_break.py      ← TrendBreak stratejisi (NautilusTrader Strategy)
├── config/
│   └── settings.py         ← Env var → config loader
└── [nautilus_trader source files from original zip]
```
