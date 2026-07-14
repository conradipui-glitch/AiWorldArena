# ADR-0006: Executive decision lifecycle stays outside the world kernel

- **Status:** Accepted
- **Date:** 2026-07-14

## Decision

LLM provider I/O выполняется внешним `ExecutiveRunner`, а не внутри `SimulationEngine.step()`.
Ядро выдаёт неизменяемый agent-scoped `DecisionTicket`, после чего принимает только
`DecisionResolution`, если head очереди и `MindBinding.revision` не изменились.

Scripted policy сохраняет синхронный `step()` как детерминированный acceptance driver.
Provider latency не изменяет игровое время. Невалидный JSON/schema получает ровно одну
repair-попытку; повторная ошибка или transport failure превращается в типизированный `wait`.

## Consequences

- Executive Layer остаётся единственным LLM gateway.
- Ответ старой модели после hot-swap не может изменить мир.
- Схемно валидное, но физически невозможное действие не ремонтируется моделью, а обычно
  отклоняется авторитетным world validator.
- Exact Decision Replay сможет подставлять сохранённый `DecisionResolution` без сети.
