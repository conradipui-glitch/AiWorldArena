# Block 2 Checkpoint

**Status:** COMPLETE
**Date:** 2026-07-15

## Реализовано

### Executive Layer

- Provider I/O вынесен из авторитетного world kernel в `ExecutiveRunner`.
- Agent-scoped decision ticket фиксирует observation и revision текущего `MindBinding`.
- Ответ модели проходит строгий single-object JSON/schema parser; extra/coerced поля запрещены.
- Невалидный ответ получает ровно одну repair-попытку, после чего применяется безопасный `wait`.
- Схемно корректное, но невозможное действие отклоняется world validator без повторного запроса к
  модели.
- Typed provider errors завершают decision безопасно; отмена и неожиданная ошибка закрывают
  cognitive budget reservation без записи секретов.
- Решения одного run сериализуются, чтобы два runner не применили один head event одновременно.

### Providers и hot-swap

- Определены единые contracts, registry, deterministic offline fake provider и Ollama adapters для
  model inventory, chat и embeddings.
- Endpoint, credentials и provider administration остаются server-controlled и не входят в intent
  или prompt.
- Ollama transport ограничивает redirects, proxy inheritance, concurrency, полный deadline,
  размер response, глубину JSON и usage metadata.
- Hot-swap сначала проверяет provider/model inventory, затем увеличивает binding revision,
  сохраняет личность, память и budget state, помечает run как modified и отбрасывает поздний ответ
  предыдущей модели.

### Память и субъективные знания

- Versioned SQLite repository хранит working, episodic, semantic и social memory отдельно от
  объективного `WorldState`, с обязательным scope `run_id + agent_id`.
- Retrieval ограничен и детерминированно учитывает semantic score, свежесть, значимость,
  confidence и историю обращений.
- Working memory сворачивается с provenance; memory и belief forgetting зависят от игрового, а не
  wall-clock времени.
- Observation projector создаёт working/social/semantic records и agent-scoped beliefs.
- Прямое наблюдение может заменить противоречивое актуальное belief; субъективное мнение не
  превращается в глобальную репутацию.

### Асинхронные социальные объекты

- Messages и offers создаются отдельно от доставки; scheduled events повторно проверяют
  доступность, а поздние/дублированные переходы безопасно пропускаются.
- Transfer атомарен и проверяет стороны, расстояние и inventory.
- Accepted offer повторно проверяет актуальные ресурсы и terms до создания versioned commitment;
  частичная мутация при отказе не допускается.
- Direct promise и минимальный commitment lifecycle поддерживают deadline, fulfilled, broken и
  expired states; pending transitions сохраняются в world snapshot.

### Persistence и provenance

- Snapshot load проверяет schema version, state hash, event chain и семантические ссылки, тайминги,
  очередь событий и sequence counters.
- CLI `resume` после успешной проверки помечает запуск `modified` и добавляет событие
  `snapshot_imported` с исходными digests и provenance `unverified_import`.
- Неключевые hashes являются контролем внутренней целостности, но не цифровой подписью источника.

## Проверено

- Изолированный живой Ollama 0.32.0 smoke с `gpt-oss:120b-cloud` прошёл inventory и один chat
  decision через реальный loopback runtime; подробности находятся в
  `docs/smoke/OLLAMA_BLOCK_2.md`.
- Обычный автоматический suite остаётся offline и использует fake provider/embedding или bounded
  mock transport.
- Полный suite: `81 passed` на Python 3.12.13.
- Coverage: 88% (`2351` statements, `275` missed).
- Headless smoke обработал 10 000 событий: `state_hash=3889e8b9a8c4617bb095e43c93bce8d3772004a74a49c1cb1d5339397b67284a`, `event_digest=7f87242f5dd2500d5d5bbc8d28493a4f10604bc5a91a199c05c5196c8ca1f7e4`.

## Security status

- Строгие provider/model boundaries, prompt isolation, resource bounds, safe fallback, snapshot
  validation и import provenance покрываются адресными тестами Block 2.
- Формальный repository-wide security scan намеренно отложен до Block 5. Промежуточный scan во
  время разработки Block 2 не был запечатан после изменения target snapshot; финального отчёта
  безопасности для этого блока нет и в checkpoint он не заявляется.

## Известные ограничения

- World snapshots и SQLite cognition repository пока не являются единым атомарным export/replay
  bundle; он появляется вместе с Decision Replay в Block 4.
- Новый вызов облачной модели не обещает побитовой повторяемости. Exact replay будет использовать
  сохранённые decision resolutions без сети.
- Phaser observer, WebSocket, browser QA и визуальное направление относятся к Block 3.
- Совместный проект, кризисный семидневный эксперимент и итоговые сравнительные метрики относятся
  к Block 4.
- Digital signatures и доверенный внешний provenance manifest не входят в Block 2.

## Checkpoint record

- Full suite: `81 passed`.
- Coverage: 88%.
- Tag: `block-2-complete`.
- Commit hash, push и GitHub Actions result фиксируются в итоговой передаче после публикации этого
  проверенного дерева; история завершённых блоков не переписывается.

## Следующий блок

Product Design exploration и Visual Observer MVP: выбранное арт-направление, Phaser-карта,
информационные панели и inspector, day/night/weather presentation, WebSocket/reconnect,
pause/speed controls и browser QA.
