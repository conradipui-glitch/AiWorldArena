# AI Society Simulation Platform

Локальная исследовательская платформа для наблюдения за возникающим поведением автономных агентов в общем мире. Мир является авторитетным, событийным и независимым от визуального клиента и языковых моделей.

## Текущий статус

**Блок 4 — Experimental MVP реализован.** Три агента могут автономно прожить семь
игровых дней на острове, пройти дождь и кризисное похолодание, обмениваться ресурсами,
давать и нарушать обещания и совместно построить хранилище. React + Phaser остаются
русскоязычным окном наблюдения, а не источником состояния. Государства, готовые рынки,
технологии, поколения и боевая система не входят в текущий scope.

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
- `docs/checkpoints/BLOCK_4.md` — фактический checkpoint четвёртого блока.
- `docs/smoke/OLLAMA_BLOCK_2.md` — отдельный живой Ollama smoke.

## Checkpoint policy

Каждый завершённый макроблок проходит полный тестовый набор, получает содержательный commit,
прямой push в `main` и tag `block-N-complete`. Force push и переписывание завершённой истории
запрещены. CI повторяет Python-проверки и TypeScript/Vite build на Windows.
