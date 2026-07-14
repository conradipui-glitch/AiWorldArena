# ADR-0009: Asynchronous messages, offers and minimal commitments

- **Status:** Accepted
- **Date:** 2026-07-14

## Decision

Сообщение и offer сначала создаются в pending-состоянии, затем отдельное scheduled event повторно
проверяет доступность получателя и переводит объект в delivered/open либо expired. Мир никогда не
ожидает ответ синхронно. Duplicate/late scheduled transition является безопасным idempotent skip.

Минимальный `Commitment` хранит стороны, bounded terms, provenance, status, deadline и version.
Принятый offer создаёт commitment; direct promise создаёт unilateral commitment. Terminal statuses
не переоткрываются. Богатая трактовка свободных terms, совместные проекты и автоматическое
сопоставление частичных вкладов остаются Block 4.

## Consequences

- Guessable ids не дают полномочий: party, visibility/range, inventory и current status всегда
  перепроверяются ядром.
- Только стороны видят message/offer/commitment в agent projection.
- Sent, delivered, expired, accepted, fulfilled и broken являются различимыми world events.
