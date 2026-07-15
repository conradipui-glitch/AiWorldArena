# AI Society Simulation Platform

Локальная исследовательская платформа для наблюдения за возникающим поведением автономных агентов в общем мире. Мир является авторитетным, событийным и независимым от визуального клиента и языковых моделей.

## Текущий статус

**Блок 5 — Research Layer реализован для локального research checkpoint.** Три агента могут автономно
прожить семь игровых дней на острове, пройти дождь и кризисное похолодание, обмениваться
ресурсами, давать и нарушать обещания и совместно построить хранилище. Каждый завершённый
запуск теперь получает проверяемый catalog entry, reproducibility manifest, JSON/Markdown/SVG
отчёт и безопасную research lineage. React + Phaser остаются русскоязычным окном наблюдения,
а не источником состояния. Государства, готовые рынки, технологии, поколения и боевая система
не входят в текущий scope. Это локальная исследовательская сборка, не публичный релиз:
формальный security audit по решению оператора отложен до отдельной подготовки публичного выпуска.

## Быстрый запуск на Windows

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\scripts\run.ps1
```

API-каркас запускается только на loopback-интерфейсе:

```powershell
.\scripts\run.ps1 -Api
```

## Визуальный наблюдатель

Подготовка клиента (один раз):

```powershell
Set-Location .\client
npm ci
Set-Location ..
```

Единый локальный запуск API и интерфейса:

```powershell
.\scripts\observer.ps1
```

После запуска откройте `http://127.0.0.1:5173`. Интерфейс полностью на русском:
на карте Phaser видны тайлы, ресурсы, постройки и агенты; есть камера, визуальная
смена дня/ночи и погода, событийная хроника, пауза, ×1/×3/×10, выбор режима перед
запуском, сохранение/загрузка и инспектор субъективного состояния агента. Браузер
получает read-only WebSocket-снимки и не является источником авторитетного состояния.
В стартовом сценарии погода уже является авторитетным законом мира и влияет на холод.

Подробная граница клиента и сервера — в `docs/OBSERVER_BLOCK_3.md`.

### Запуск двойным кликом

После однократной подготовки Python-окружения и `client/node_modules` можно просто открыть
`START_AIWORLD_ARENA.bat` в корне репозитория. Он не создаст второй экземпляр готового
наблюдателя, дождётся API и UI на `127.0.0.1`, затем откроет браузер. Ошибка подготовки
зависимостей или занятых портов выводится в окно запуска; логи `work/observer-*.log` появляются
после попытки поднять дочерние процессы.

Если стандартные порты заняты, можно задать пару локальных портов перед запуском:

```powershell
$env:AIWORLD_API_PORT = 8011
$env:AIWORLD_UI_PORT = 5175
.\START_AIWORLD_ARENA.bat
```

Для автоматической проверки без открытия браузера предусмотрены `AIWORLD_NO_BROWSER=1` и
`AIWORLD_NO_PAUSE=1`; обычному пользователю их задавать не нужно.

## Семидневный эксперимент и exact replay

Полный воспроизводимый Scripted Test Mode:

```powershell
.\scripts\experiment.ps1 -Mode scripted -Name three-agents-seven-days
```

Команда создаёт один проверяемый JSON bundle в `outputs/experiments/`, экспортирует
решения, события, финальное состояние, cognition, метрики и журнал вмешательств, а
затем сразу проверяет exact Decision Replay. Повторная проверка не вызывает сеть:

```powershell
.\.venv\Scripts\python.exe -m ai_society.cli replay-experiment three-agents-seven-days
```

Controlled Mode принимает одну общую Ollama-модель, Natural Mode — три назначения:

```powershell
.\scripts\experiment.ps1 -Mode controlled -Models 'qwen3:8b'
.\scripts\experiment.ps1 -Mode natural -Models 'qwen3:8b','gemma3:12b','deepseek-r1:8b'
```

Повторный живой вызов Ollama не считается exact replay: он является новым
экспериментальным прогоном. Точные контракты — в `docs/EXPERIMENT_BLOCK_4.md`.

## Исследовательский слой

Любой запуск, созданный командой `experiment`, автоматически получает bundle, manifest и
читабельный отчёт. Базовый Scripted run маркируется `clean`; новый запуск тех же условий —
`experimental`; ветка от проверенного начального снимка или запуск с явной аннотацией
исследователя — `modified`.

```powershell
# Каталог проверенных запусков
.\scripts\research.ps1 catalog-experiments

# Новый вызов тех же моделей; это не exact replay
.\scripts\research.ps1 rerun-experiment three-agents-seven-days --name rerun-01

# Минимальная репликация требует не менее двух новых запусков
.\scripts\research.ps1 replicate-experiment three-agents-seven-days --prefix replica --count 2

# Полная дочерняя история только от снимка bundle.initial_state (игровая минута 0)
.\scripts\research.ps1 branch-experiment three-agents-seven-days --name branch-01

# Сравнение и регенерация JSON/Markdown/SVG отчёта
.\scripts\research.ps1 compare-experiments three-agents-seven-days rerun-01
.\scripts\research.ps1 report-experiment three-agents-seven-days
```

Research API доступен только на чтение: `GET /v1/experiments`, manifest, report и comparison.
Он не раскрывает cognition и не запускает модели из браузера. Полный контракт и доказанные
границы — в `docs/RESEARCH_BLOCK_5.md`.

Проверки:

```powershell
.\scripts\test.ps1
```

## Ollama и модели

Доступные модели всегда запрашиваются у локального Ollama runtime, без жёсткого списка:

```powershell
.\.venv\Scripts\python.exe -m ai_society.cli ollama-models
```

Изолированный реальный smoke одной модели:

```powershell
.\scripts\ollama-smoke.ps1 -Model 'gpt-oss:120b-cloud' -NoStructuredOutput
```

Обычные тесты не вызывают сеть и используют deterministic fake provider/embedding. Endpoint и
credentials задаются только серверной конфигурацией; agent intent и API payload не могут их менять.

## Headless CLI

```powershell
.\.venv\Scripts\python.exe -m ai_society.cli run --seed 42 --events 1000 --agents 3
```

Команда печатает детерминированный hash состояния и digest цепочки событий. Snapshot-файлы
сохраняются только в `data/snapshots/` и не принимают произвольные пути. При `resume` загруженный
snapshot проходит schema, hash-chain и семантическую проверку, после чего запуск явно помечается
как `modified`/непроверенный импорт. Неключевые hashes обнаруживают повреждение и несогласованность,
но не удостоверяют внешнее происхождение файла.

Для полностью зафиксированного окружения вместо extras можно установить `requirements.lock`, затем сам пакет с `--no-deps`.

## Архитектурные документы

- `docs/UNIFIED_ARCHITECTURE_BASELINE.md` — утверждённая архитектурная база.
- `docs/MVP_SCOPE.md` — точная граница MVP.
- `docs/ROADMAP.md` — пять блоков и дальние горизонты.
- `docs/ACCEPTANCE_MATRIX.md` — проверяемые критерии.
- `docs/security/THREAT_MODEL.md` — репозиторная модель угроз.
- `docs/checkpoints/BLOCK_1.md` — фактический checkpoint первого блока.
- `docs/checkpoints/BLOCK_2.md` — состав и статус checkpoint второго блока.
- `docs/OBSERVER_BLOCK_3.md` — запуск и ограничения Visual Observer MVP.
- `docs/EXPERIMENT_BLOCK_4.md` — семидневный сценарий, export, метрики и replay.
- `docs/RESEARCH_BLOCK_5.md` — каталог, manifest, rerun, replication, branch, reports и ограничения.
- `docs/checkpoints/BLOCK_4.md` — фактический checkpoint четвёртого блока.
- `docs/checkpoints/BLOCK_5.md` — фактический checkpoint исследовательского слоя.
- `docs/smoke/OLLAMA_BLOCK_2.md` — отдельный живой Ollama smoke.

## Checkpoint policy

Каждый завершённый макроблок проходит полный тестовый набор, получает содержательный commit,
прямой push в `main` и tag `block-N-complete`. Force push и переписывание завершённой истории
запрещены. CI повторяет Python-проверки и TypeScript/Vite build на Windows.
