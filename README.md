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

## Branch Strategy

- `main`: Production-ready code
- `dev`: Development branch
- `feature/*`: Feature branches
