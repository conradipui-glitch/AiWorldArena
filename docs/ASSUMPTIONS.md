# Assumptions

## Active

- Python 3.12 unit/integration suite не вызывает сеть; реальный Ollama smoke запускается отдельно.
- Game time хранится целым числом минут.
- Более высокое значение `hunger` означает больший голод; более высокое `energy` означает больший запас энергии.
- Базовый visibility radius равен двум клеткам по Manhattan distance.
- Scripted policy — детерминированный тестовый драйвер, а не предписанная стратегия LLM-агентов.
- World snapshots остаются canonical JSON envelopes; единый Block 4 experiment bundle атомарно
  упаковывает начальное/финальное состояние, cognition export, решения, события, метрики и журнал
  вмешательств. Replay заново исполняет сохранённые решения, а cognition остаётся проверяемой
  зафиксированной частью записи и не извлекается повторно.
- Неключевые snapshot/event hashes проверяют внутреннюю целостность, но не являются подписью и не
  подтверждают происхождение внешнего файла.
- CLI `resume` рассматривает snapshot как непроверенный импорт: сохраняет исходные state/event
  digests в событии, выставляет `run.modified=true` и не объявляет продолжение чистой репликацией.
- API блока 1 является локальным in-memory control plane и не считается публичным многопользовательским сервисом.

## Validated in Block 2

- Ollama 0.32.0 dynamic inventory и real `gpt-oss:120b-cloud` chat smoke прошли через loopback runtime.
- Ollama `/api/embed` contract проверен bounded mock transport; production adapter принимает до 4096 finite dimensions.

## Validated in Block 4

- Scripted Test Mode автономно достигает ровно 10 080 игровых минут с тремя живыми агентами.
- Exact Decision Replay воспроизводит итоговые state hash и event digest без provider/network calls.
- Natural Mode требует минимум два разных model binding; Controlled Mode требует один общий binding.
- Дождь и кризисное похолодание являются авторитетными событиями мира, а не UI-декорацией.

## Validated in Block 5

- `research/` внутри fixed experiment output root хранит только derived catalog, manifests,
  reports, comparisons и branch snapshots. Он не импортируется simulation kernel и не получает
  write path к живому миру.
- `clean`, `modified` и `experimental` — composable provenance marks. Они описывают метод
  получения артефакта, а не качество или ценность поведения агентов.
- `experimental rerun` и `replica` создают новый `run_id` через `run_nonce`, но сохраняют
  initial world/personality contract. Повторный вызов LLM не обещает совпадение решений.
- Минимальная ветка Block 5 начинается только от `bundle.initial_state` в игровой минуте 0.
  Bundle v1 не содержит атомарной mid-run cognition snapshot, поэтому ветвление из середины
  истории не заявляется как реализованное.
- Аннотация исследователя фиксируется в intervention journal и маркирует export `modified`, но
  не меняет authoritative world. Свободное редактирование мира не является control path MVP.
- Reproducibility manifest и canonical digests обнаруживают повреждение и рассогласование; они
  не являются цифровой подписью внешнего происхождения.

## Deferred validation

- Performance targets выше десяти scripted agents устанавливаются после работающего MVP.
- Live Ollama embedding smoke откладывается до появления подходящей локальной embedding model.
- Подписанный provenance, branch из промежуточной cognition snapshot, массовые репликации,
  causal graph и статистические выводы выходят за MVP. Они не подменяются нынешними reports.
- Формального repository-wide security scan или security certification для локального checkpoint
  нет: оператор явно отложил его до подготовки публичного релиза.
