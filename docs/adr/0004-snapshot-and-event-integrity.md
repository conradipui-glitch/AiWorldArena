# ADR-0004: Canonical snapshots and hash-chained events

- **Status:** Accepted
- **Date:** 2026-07-14

## Decision

Snapshot является версионированным envelope с полным authoritative state и event log. Event record
включает hash предыдущего события. Имена snapshot ограничены безопасным slug внутри fixed root.

Load проверяет версию schema, canonical state hash, event hash chain и семантические инварианты
мира: ссылки на entities, координаты, тайминги, очередь scheduled events и монотонные sequence
counters. CLI `resume` после успешной проверки всё равно рассматривает файл как внешний импорт:
запуск получает `modified=true` и событие `snapshot_imported` с исходными state/event digests и
provenance `unverified_import`.

## Consequences

Save/load сохраняет PRNG и очередь. Повреждённая цепочка, неизвестная версия и самосогласованный,
но семантически некорректный world state отклоняются.

SHA-256 hashes здесь являются контролем целостности, а не аутентичности: сторона, способная изменить
файл, может пересчитать неключевой hash. Поэтому импортированный snapshot нельзя автоматически
считать доказанно происходящим из доверенного run. Подписи/ключевой provenance manifest остаются
за пределами Block 2.

Решение обеспечивает фундамент Decision Replay, но не обещает повторяемость новых облачных
LLM-вызовов. World snapshot и SQLite cognition пока сохраняются раздельно; единый атомарный bundle
добавляется вместе с Decision Replay в Block 4.
