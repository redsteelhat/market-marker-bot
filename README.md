# market-marker-bot

Market making bot for cryptocurrency exchanges.

## Technology Stack

- **Python**: 3.11+
- **HTTP Client**: httpx
- **WebSocket**: websockets
- **Data Processing**: pandas, numpy
- **Configuration**: Pydantic v2 + python-dotenv (.env files)

## Project Structure

```
src/
  core/         # Domain models, config
  data/         # Market data client & order book
  strategy/     # Market making logic
  risk/         # Risk & limit controls
  execution/    # Order sending, cancel, routing
  backtest/     # Simulation & backtest engine
  monitoring/   # Log, metrics, alerting
  apps/         # CLI / runner scripts
tests/
```

## Setup

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Copy `.env.example` to `.env` and configure:
```bash
cp .env.example .env
```

3. Configure your `.env` file with Binance API credentials:
```env
EXCHANGE_API_KEY=your_api_key_here
EXCHANGE_API_SECRET=your_api_secret_here
EXCHANGE_BASE_URL=https://fapi.binance.com  # or https://testnet.binancefuture.com for testnet
EXCHANGE_WS_URL=wss://fstream.binance.com  # or wss://stream.binancefuture.com for testnet
EXCHANGE_TESTNET=true  # Set to false for production
```

## Usage

### Run the bot:

**Paper Trading Mode (Default - Live Data + Local Simulation):**
```bash
python -m src.apps.main run --mode paper_exchange
```

**Run with specific symbol:**
```bash
python -m src.apps.main run --mode paper_exchange --symbol BTCUSDT
```

**Dry Run Mode (No Orders, Logging Only):**
```bash
python -m src.apps.main run --mode dry_run
```

**Backtest Mode (Requires Historical Data):**
```bash
python -m src.apps.main run --mode backtest --symbol BTCUSDT
```

**Check bot status with detailed metrics:**
```bash
python -m src.apps.main status
```

**Test scenarios:**
```bash
# Test inventory limit enforcement
python scripts/test_scenarios.py inventory

# Test kill switch trigger
python scripts/test_scenarios.py killswitch

# Test order limit enforcement
python scripts/test_scenarios.py orders
```

**Environment check:**
```bash
python scripts/check_env.py
```

## Testing

### Run unit tests:
```bash
pytest tests/ -v
```

### Run integration tests (requires testnet API credentials):
```bash
pytest -m integration -v
```

**Note:** Integration tests require real Binance testnet API credentials and will make actual API calls.

## Documentation

- [Specification & Strategy Framework](docs/SPEC.md) - Hedef metrikler, işlem frekansı, sermaye planı, borsa seçimi
- [Strategy Design (FAZ 2)](docs/STRATEGY_DESIGN.md) - Strateji tasarım sözleşmesi (V1 PMM, V2 AS), parametreler, risk kuralları, PnL modelleri
- [Architecture & Development Order](docs/ARCHITECTURE.md) - Mimari tasarım, modül yapısı, geliştirme sırası, veri akışı
- [Development Phases (FAZ 3-6)](docs/DEVELOPMENT_PHASES.md) - Sistem mimarisi, strateji motoru, risk katmanı, backtest altyapısı
- [Testing Guide](docs/TESTING_GUIDE.md) - Sistematik test ve kalibrasyon rehberi

## Branch Strategy

- `main`: Production-ready code
- `dev`: Development branch
- `feature/*`: Feature branches
