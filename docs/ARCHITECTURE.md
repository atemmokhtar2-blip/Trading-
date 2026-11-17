# Architecture — initial decisions

## Product direction

The first release is a private, single-account research and demo-trading system. The design must not assume that it will remain single-user: account identity, strategy configuration, audit events, and execution ownership must have explicit boundaries before multi-user subscriptions are introduced.

## Components and trust boundaries

1. **Domain core (Python):** deterministic risk policy, typed trade proposals, strategy interfaces, and state transitions. No network or broker SDK imports.
2. **Research layer:** historical data normalization, feature calculations, backtesting, and walk-forward evaluation. Research output is not automatically executable.
3. **AI analysis adapter:** optional provider interface. AI output is untrusted input; it can annotate or rank a candidate but cannot override domain rules, risk limits, or execution permissions.
4. **MT5 adapter (Windows):** the only component allowed to communicate with the MetaTrader terminal. It validates symbol metadata, volume steps, tick sizes, stops, filling mode, and account state.
5. **Control plane (Railway-compatible):** Telegram/API interface, PostgreSQL, configuration delivery, and monitoring. It does not host the Windows MT5 terminal.
6. **Observability:** structured logs, immutable decision/audit records, health checks, and alerts.

## Initial deployment topology

- Local development and offline tests first.
- Windows host/VPS for the MT5 terminal adapter when integration begins.
- Railway only for services that are compatible with its Linux/container runtime, after costs and operational requirements are reviewed.
- Secrets are injected through environment/secret management and never committed.

## Execution safety invariants

- The risk gate runs immediately before every order submission.
- No order is submitted without a valid, fresh account snapshot and explicit stop-loss calculation.
- Unknown order outcomes are reconciled against broker positions/orders before any retry.
- Every order has a stable strategy identifier and unique client-side correlation/idempotency key where supported.
- A kill switch must block new entries even if AI, Telegram, or strategy services are unavailable.
- Closing or reducing exposure must remain possible when new entries are disabled.
- Manual positions must not be modified unless explicitly configured and authorized.

## Future multi-user path

Before public subscriptions, add tenant-scoped identities, per-user broker credential isolation, authorization checks on every request, subscription entitlements, billing webhooks with replay protection, rate limits, audit trails, and resource quotas. No shared global account state or shared credentials.

## Why this architecture

The design keeps deterministic safety rules independent of AI and broker APIs. It also lets research, simulation, and unit tests run on machines without MetaTrader 5 installed. This reduces coupling and makes later migration to a public service safer.
