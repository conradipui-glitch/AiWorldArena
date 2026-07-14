# ADR-0003: Objective state and subjective knowledge are separate

- **Status:** Accepted
- **Date:** 2026-07-14

## Decision

Физическая клетка не содержит `explored`. Исследованность, beliefs, confidence и мнения о репутации принадлежат конкретной личности.

## Consequences

Prompt и API обязаны строиться из agent-scoped projection. Analytics может читать объективный мир, но не возвращает это знание агенту.
