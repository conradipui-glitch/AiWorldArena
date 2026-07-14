# AI Society Simulation Platform

Локальная исследовательская платформа для наблюдения за возникающим поведением автономных агентов в общем мире. Мир является авторитетным, событийным и независимым от визуального клиента и языковых моделей.

## Текущий статус

**Блок 1 — Architecture Freeze + Headless World Kernel завершён локально.** В этом блоке нет Phaser-клиента, реальных LLM, RAG, торговли, государств или боевой системы.

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

Проверки:

```powershell
.\scripts\test.ps1
```

## Headless CLI

```powershell
.\.venv\Scripts\python.exe -m ai_society.cli run --seed 42 --events 1000 --agents 3
```

Команда печатает детерминированный hash состояния и digest цепочки событий. Snapshot-файлы сохраняются только в `data/snapshots/` и не принимают произвольные пути.

Для полностью зафиксированного окружения вместо extras можно установить `requirements.lock`, затем сам пакет с `--no-deps`.

## Архитектурные документы

- `docs/UNIFIED_ARCHITECTURE_BASELINE.md` — утверждённая архитектурная база.
- `docs/MVP_SCOPE.md` — точная граница MVP.
- `docs/ROADMAP.md` — пять блоков и дальние горизонты.
- `docs/ACCEPTANCE_MATRIX.md` — проверяемые критерии.
- `docs/security/THREAT_MODEL.md` — репозиторная модель угроз.
- `docs/checkpoints/BLOCK_1.md` — фактический checkpoint первого блока.

## Checkpoint policy

Каждый завершённый макроблок проходит локальные тесты, получает отдельный commit и после появления GitHub remote отправляется в приватный репозиторий. CI повторяет compile и pytest на Windows/Python 3.12.
