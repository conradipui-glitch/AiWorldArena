# ADR-0005: Model and imported content are untrusted

- **Status:** Accepted
- **Date:** 2026-07-14

## Decision

Model output, messages, journals, contracts, imported scenarios и provider responses считаются недоверенными данными. Исполняемый код из них запрещён. Executive Layer применяет строгие схемы и capability checks.

## Consequences

Provider endpoints задаются серверным оператором, а не моделью. UI экранирует generated text. Control, observation, intervention и provider administration будут отдельными capability surfaces.
