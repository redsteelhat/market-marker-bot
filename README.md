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

## Documentation

- [Specification & Strategy Framework](docs/SPEC.md) - Hedef metrikler, işlem frekansı, sermaye planı, borsa seçimi
- [Strategy Design (FAZ 2)](docs/STRATEGY_DESIGN.md) - Strateji tasarım sözleşmesi (V1 PMM, V2 AS), parametreler, risk kuralları, PnL modelleri
- [Architecture & Development Order](docs/ARCHITECTURE.md) - Mimari tasarım, modül yapısı, geliştirme sırası, veri akışı
- [Development Phases (FAZ 3-6)](docs/DEVELOPMENT_PHASES.md) - Sistem mimarisi, strateji motoru, risk katmanı, backtest altyapısı

## Branch Strategy

- `main`: Production-ready code
- `dev`: Development branch
- `feature/*`: Feature branches
