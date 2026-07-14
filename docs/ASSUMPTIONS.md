# Assumptions

## Active

- Блок 1 использует Python 3.12 и не вызывает сеть во время simulation tests.
- Game time хранится целым числом минут.
- Более высокое значение `hunger` означает больший голод; более высокое `energy` означает больший запас энергии.
- Базовый visibility radius равен двум клеткам по Manhattan distance.
- Scripted policy — детерминированный тестовый драйвер, а не предписанная стратегия LLM-агентов.
- MVP хранит snapshots в локальной SQLite/JSON-совместимой абстракции; блок 1 начинает с канонического JSON envelope, а SQLite repository добавляется вместе с памятью в блоке 2.
- API блока 1 является локальным in-memory control plane и не считается публичным многопользовательским сервисом.

## Deferred validation

- Совместимость актуального Ollama API проверяется в блоке 2 реальным smoke test.
- Размер тайла, арт-направление и плотность UI выбираются через Product Design в блоке 3.
- Performance targets выше десяти scripted agents устанавливаются после работающего MVP.
