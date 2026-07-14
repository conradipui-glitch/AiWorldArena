# ADR-0002: Deterministic event-driven kernel

- **Status:** Accepted
- **Date:** 2026-07-14

## Decision

Мир продвигается обработкой scheduled events. Порядок задаётся `(due_minute, sequence)`. Собственный версионированный 64-bit PRNG и все counters входят в snapshot.

## Consequences

Симуляция не зависит от частоты кадров и wall-clock latency. Асинхронные model responses в следующих блоках должны превращаться в игровые события по явным правилам, а не по порядку завершения сетевых запросов.
