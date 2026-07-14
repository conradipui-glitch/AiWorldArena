# Block 1 Checkpoint

**Status:** COMPLETE LOCALLY
**Date:** 2026-07-14

## Реализовано

- Утверждённая Unified Architecture Baseline, MVP scope, roadmap, assumptions и пять ADR.
- Repository-scoped threat model и security invariants.
- Pydantic domain models без смешения личности, тела, mind binding и agent-scoped knowledge.
- Детерминированный островной world generator с собственным SplitMix64 PRNG.
- Event-driven scheduler с игровыми минутами и стабильным tie-break sequence.
- Scripted policy и действия observe, move, gather, consume, rest, wait.
- Authoritative state, частичное observation projection и needs progression.
- Append-only event hash chain, canonical state hashing и безопасные fixed-root snapshots.
- Exact save/load/continue для scripted мира.
- Headless CLI, PowerShell launch/test scripts и минимальный loopback FastAPI control plane.
- Windows GitHub Actions workflow и locked Python dependencies.

## Проверено

- 20 автоматических тестов прошли.
- 10 000 scheduled events обработаны без остановки.
- Seed и scripted policy дают одинаковые hashes.
- Snapshot tampering, event tampering и path traversal обнаруживаются.
- 1, 3 и 10 scripted agents работают без hardcode сценария.
- API запускается на `127.0.0.1` и отвечает на health/create/advance/read.

## Известные ограничения

- Snapshot repository блока 1 использует canonical JSON; SQLite persistence появляется вместе с memory repository в блоке 2.
- API registry является in-memory и не имеет WebSocket — это осознанная граница до блока 3.
- Действия меняют состояние в момент принятия и блокируют следующее решение своей длительностью; отдельные completion events будут нужны для многоэтапных действий блока 2/4.
- Реальный Ollama runtime, embeddings, память, async dialogue и commitments отсутствуют до блока 2.
- GitHub remote/push ожидает установленный и авторизованный `gh`.

## Следующий блок

Executive Layer, provider adapters, partial prompt construction, strict repair/fallback, four-layer memory with compaction/forgetting, beliefs/confidence, async messages и минимальный commitment lifecycle.
