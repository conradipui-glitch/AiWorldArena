# Блок 4 — Experimental MVP

## Фиксированный сценарий

`ExperimentConfig` создаёт остров 48×48 или 64×64, ровно три личности с одинаковым телом и
стартовым инвентарём и авторитетную границу в 10 080 игровых минут. Посадочные клетки различны,
но образуют один локальный лагерь. Каждый агент получает только собственное наблюдение,
исследованную карту, доступные сообщения, договоры и совместные проекты.

Погодный закон содержит дождь и одно кризисное похолодание. Смена погоды проходит через
scheduled world events, влияет на температуру тела и фиксируется в event log. Семидневный конец
тоже является авторитетным системным событием и останавливает очередь без ручного управления.

Scripted Test Mode является приёмочным драйвером, а не предписанием поведения LLM. Он гарантирует
проверяемые эпизоды: добровольное присоединение и отказ от проекта, раздельные вклады двух
участников, завершение общего хранилища, store/take, offer/accept, передача ресурса, выполненное и
нарушенное обещания. После этих эпизодов агенты возвращаются к общей survival policy.

## Режимы

- `scripted` — полностью локальный детерминированный acceptance run;
- `controlled` — одна и та же server-validated Ollama binding у трёх личностей;
- `natural` — три назначения, минимум два разных provider/model binding.

Natural и Controlled используют тот же `ExecutiveLayer`, строгие intents, один repair и safe
fallback. Обычный тест повторно невалидного model output подтверждает, что эксперимент
продолжается. Полный семидневный CI-прогон выполняется в scripted режиме, чтобы тесты не зависели
от сети или установленной модели.

## Экспорт и replay

`scripts/experiment.ps1` записывает `experiment-bundle-v1` в фиксированный output root. Bundle
содержит config, initial/final world, решения, events, cognition, metrics и interventions. Имена
файлов — safe slug; symlink, traversal, превышение 128 MiB, неизвестная schema, повреждённая event
chain или несовпадающий digest отклоняются.

`replay-experiment` не создаёт provider и не выполняет retrieval. Каждое решение применяется
только к совпадающему ticket, после чего проверяются итоговые state hash и event digest.

Минимальные метрики собираются по каждому агенту: жизнь, решения, успехи/отклонения, добыча и
затраты, постройки, взаимодействия, offers, promises, retrieval, model requests, tokens и latency.
Отсутствие вмешательств выражается пустым типизированным журналом и нулевой метрикой, а не
неявным отсутствием данных.

## Локальный запуск

```powershell
.\scripts\experiment.ps1 -Mode scripted -Name three-agents-seven-days
.\.venv\Scripts\python.exe -m ai_society.cli replay-experiment three-agents-seven-days
```

Visual Observer по умолчанию запускает тот же русскоязычный scripted experiment на карте 48×48.
Погода, температура, кризис, постройки и социальные события приходят из серверного snapshot.

## Честные ограничения

- Full seven-day Natural/Controlled run зависит от скорости и доступности выбранных Ollama-моделей.
- UI не редактирует индивидуальные model binding; их назначает headless experiment CLI.
- Cognition сохраняется в bundle, но не пересчитывается в exact replay.
- Minimal replication, branching, comparison, divergence и подписанный provenance — Block 5.
