# Assumptions

## Active

- Python 3.12 unit/integration suite не вызывает сеть; реальный Ollama smoke запускается отдельно.
- Game time хранится целым числом минут.
- Более высокое значение `hunger` означает больший голод; более высокое `energy` означает больший запас энергии.
- Базовый visibility radius равен двум клеткам по Manhattan distance.
- Scripted policy — детерминированный тестовый драйвер, а не предписанная стратегия LLM-агентов.
- World snapshots остаются canonical JSON envelopes; cognition Block 2 хранится в versioned SQLite. Единый atomic world+cognition replay bundle добавляется вместе с Decision Replay в Block 4.
- Неключевые snapshot/event hashes проверяют внутреннюю целостность, но не являются подписью и не
  подтверждают происхождение внешнего файла.
- CLI `resume` рассматривает snapshot как непроверенный импорт: сохраняет исходные state/event
  digests в событии, выставляет `run.modified=true` и не объявляет продолжение чистой репликацией.
- API блока 1 является локальным in-memory control plane и не считается публичным многопользовательским сервисом.

## Validated in Block 2

- Ollama 0.32.0 dynamic inventory и real `gpt-oss:120b-cloud` chat smoke прошли через loopback runtime.
- Ollama `/api/embed` contract проверен bounded mock transport; production adapter принимает до 4096 finite dimensions.

## Deferred validation

- Размер тайла, арт-направление и плотность UI выбираются через Product Design в блоке 3.
- Performance targets выше десяти scripted agents устанавливаются после работающего MVP.
- Live Ollama embedding smoke откладывается до появления подходящей локальной embedding model.
- Формальный repository-wide security scan и release security audit выполняются в блоке 5. Попытка
  сканирования во время разработки Block 2 не была запечатана после изменения target snapshot;
  финальный security report для Block 2 не существует.
