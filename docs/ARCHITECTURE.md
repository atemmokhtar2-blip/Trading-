# Architecture — Binance-first, Railway-hosted

## Product direction

The first release is a private, single-account research and paper-trading system. The complete application is intended to run on Railway. Binance Spot is the first exchange target, but domain logic must not depend on Binance-specific SDK objects or API responses.

## Components and trust boundaries

1. **Domain core (Python):** deterministic risk policy, typed trade intents, portfolio accounting, and state transitions. No network, Telegram, or exchange SDK imports.
2. **Research layer:** historical data normalization, feature calculations, backtesting, and walk-forward evaluation. Research output is not automatically executable.
3. **Market-data adapter:** obtains public Binance Spot market data over HTTPS/WebSocket, validates and normalizes it, and emits domain bars/quotes. Public market-data ingestion must work without API credentials.
4. **Exchange adapter (Binance Spot):** isolated integration boundary for exchange metadata, account snapshots, Testnet order submission, order-status lookup, and reconciliation. The first authenticated environment is Spot Testnet only. Production endpoints and live order submission remain disabled.
5. **AI analysis adapter:** optional provider interface. AI output is untrusted input; it can annotate or rank a candidate but cannot override domain rules, risk limits, or execution permissions.
6. **Railway application services:** the Telegram bot service and trading worker run from the same repository as separate Railway services/processes. PostgreSQL is hosted in the same Railway project. No Windows machine or desktop trading terminal is required.
7. **Observability:** structured logs, immutable decision/audit records, health checks, readiness checks, and alerts.

## Initial Railway topology

- **bot service:** receives Telegram updates (webhook or supported polling mode), handles user/operator commands, and reads durable state.
- **trading-worker service:** owns market-data subscriptions, strategy scheduling, risk evaluation, simulation, and later Testnet execution/reconciliation.
- **PostgreSQL:** stores configuration, strategy/run versions, audit events, order intents, exchange order identifiers, and portfolio snapshots.
- The worker must use a database-backed lease or equivalent distributed lock so only one active worker owns a given account/strategy execution stream. A restart must not duplicate an order.
- Both services must expose health/readiness behavior suitable for Railway restarts and deployments. Graceful shutdown must stop new work and persist/reconcile in-flight state.
- Railway variables hold runtime configuration and secrets. Secrets are never written to Git, database audit payloads, or logs.

## Binance integration policy

- Start with Binance Spot only. Margin, Futures, leverage, and short selling are excluded from the initial product.
- Public market data is unauthenticated and must be separated from private account/order credentials.
- The first authenticated exchange environment is Binance Spot Testnet. Testnet base URLs must be explicit configuration, not guessed or silently switched.
- API keys must have the minimum permissions required. Withdrawal permission must never be enabled. Restrict key IP access where the exchange/account setup supports it.
- Production credentials and production order endpoints are not accepted by the initial application configuration.
- Respect exchange rate limits, timestamp/signature requirements, symbol filters, quantity/price increments, minimum notional, and order-state transitions.
- A request timeout does not mean an order failed. Reconcile by client order identifier and exchange order state before any retry.
- WebSocket streams are not the sole source of truth for account/order state; periodically reconcile against REST snapshots.

## Execution safety invariants

- The deterministic risk gate runs immediately before every order submission.
- No order is submitted without a fresh market/account snapshot and a valid protective-stop/risk calculation appropriate to the instrument.
- Unknown order outcomes are reconciled against exchange orders and balances before any retry.
- Every order has a stable strategy identifier and unique client-side correlation/idempotency key where supported.
- A kill switch blocks new entries even if AI, Telegram, or strategy services are unavailable.
- Closing or reducing exposure remains possible when new entries are disabled.
- The system never assumes an exchange accepted an order merely because the request was sent.

## Future multi-user path

Before public subscriptions, add tenant-scoped identities, per-user credential isolation, authorization checks on every request, subscription entitlements, billing webhook replay protection, rate limits, audit trails, and resource quotas. No shared global account state or shared credentials.

## Why this architecture

The domain core stays deterministic and exchange-independent. Binance-specific behavior is confined to adapters, while Railway runs the bot, worker, and database without a desktop terminal or separate Windows host. Research and simulation remain executable offline.
