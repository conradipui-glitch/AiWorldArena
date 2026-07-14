# ADR-0004: Canonical snapshots and hash-chained events

- **Status:** Accepted
- **Date:** 2026-07-14

## Decision

Snapshot является версионированным envelope с полным authoritative state и event log. Event record включает hash предыдущего события. Имена snapshot ограничены безопасным slug внутри fixed root.

## Consequences

Save/load сохраняет PRNG и очередь. Повреждённая цепочка отклоняется. Это обеспечивает фундамент Decision Replay, но не обещает повторяемость новых облачных LLM-вызовов.
