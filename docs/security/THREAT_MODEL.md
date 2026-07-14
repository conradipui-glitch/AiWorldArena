# Repository Threat Model

## Overview

Репозиторий реализует локальную исследовательскую платформу с авторитетным Python world kernel, будущим LLM Executive Layer, FastAPI control/observation API, браузерным клиентом и сохраняемыми экспериментами. Наиболее ценные активы: целостность мира и replay, конфиденциальность памяти и provider credentials, изоляция знаний агентов, достоверность исследовательских результатов и безопасность локальной машины оператора.

## Threat Model, Trust Boundaries, and Assumptions

### Trust boundaries

1. **Operator ↔ local API.** Оператор доверен управлять экспериментом; браузерные страницы, расширения и процессы на машине не получают это доверие автоматически.
2. **World kernel ↔ LLM providers.** Model prompts и responses проходят через единственный Executive Layer. Provider и модель недоверенны.
3. **Agent-scoped knowledge ↔ authoritative world.** Агент не должен получить скрытые клетки, чужую память или объективную аналитику.
4. **Runtime ↔ persistence/import/export.** Snapshot, сценарии, договоры, журналы и replay bundles являются недоверенными файлами при загрузке.
5. **Simulation ↔ analytics/observer.** Analytics имеет read-only доступ; обратного command path нет. Вмешательство идёт через отдельный control path и фиксируется.
6. **Run/branch ↔ run/branch.** Replication и branching используют отдельные namespaces и immutable parent snapshot references.

### Input ownership

- **Attacker/model-controlled:** LLM output, agent messages, names, agreement terms, imported experiment bundles, browser payloads, WebSocket frames и потенциально provider responses.
- **Operator-controlled:** seed, model assignment, server-side endpoint configuration, experiment parameters и explicit interventions.
- **Developer-controlled:** world rules, schemas, migrations, action executors и dependency configuration.

### Security invariants

- Только world kernel изменяет authoritative state.
- Каждое действие проверяет capability, восприятие, расстояние, владение и ресурсы.
- Agent projection не содержит скрытых данных.
- Event chain и snapshots обнаруживают повреждение; exact replay не вызывает сеть.
- Snapshot/import paths остаются внутри configured root; executable deserialization отсутствует.
- Secrets никогда не попадают в prompts, events, snapshots, logs или exports.
- API слушает loopback по умолчанию; внешний режим требует отдельной security configuration.
- Analytics и UI не имеют неаудируемого write path.

## Attack Surface, Mitigations, and Attacker Stories

### Model and persistent-content injection

Модель или найденный журнал может пытаться изменить правила, извлечь скрытые данные или сохранить инструкцию для будущих prompts. Контроль: typed intents, `extra=forbid`, field limits, provenance labels, data/instruction separation и capability validation. Сгенерированный текст рендерится как text, не HTML.

### API, browser and WebSocket

Реалистичный локальный attacker — вредоносная веб-страница или другой процесс, обращающийся к loopback API. Контроль: Host/Origin validation, same-origin policy, без wildcard CORS, request limits, schema validation, WebSocket auth/backpressure в блоке 3 и отдельные read/control capabilities.

### Provider endpoints and secrets

Произвольный endpoint создаёт SSRF и канал утечки prompts/credentials. Endpoint задаётся только server-side оператором, redirects запрещаются, local/cloud режимы различаются, credentials читаются из environment/secret storage и редактируются при export.

### Persistence and imports

Traversal, symlink escape, oversized JSON и unsafe deserialization могут повредить файлы или выполнить код. Block 1 использует fixed-root slug names, canonical JSON, size/schema checks и hash-chain verification. Pickle, executable YAML, dynamic import и shell запрещены.

### Research integrity

Подмена event log, смешение branch namespaces или незаписанное вмешательство способно сфальсифицировать эксперимент. Контроль: canonical hashes, immutable provenance, explicit run status (`clean`, `modified`, `experimental`, позднее `tampered/invalid`), version manifest и offline replay.

### Out of scope for the local MVP

Публичный internet hosting, multi-tenant isolation и hostile plugin execution не поддерживаются. Если API выводится за loopback, эти предположения перестают действовать и требуется отдельная deployment threat model.

## Severity Calibration (Critical, High, Medium, Low)

### Critical

- Импортированный snapshot или сценарий выполняет произвольный код на машине оператора.
- Model-controlled endpoint или payload извлекает provider credentials и обеспечивает дальнейший compromise.

### High

- Агент систематически получает чужую память или полный authoritative world, делая исследования недостоверными.
- Неавторизованный API caller изменяет мир без intervention event.
- Подмена replay/event chain принимается как чистый воспроизводимый запуск.

### Medium

- Persistent XSS в observer UI через message/contract text при локальном доверенном API.
- Resource exhaustion через oversized model response, import или WebSocket backlog.
- Traversal ограничен sandboxed snapshot directory и не даёт чтения секретов.

### Low

- Некритичная утечка публичных метрик локального scripted run.
- Неполная диагностика отклонённого действия без изменения authoritative state.
- Ошибка developer-only CLI, требующая локального доверенного доступа и не затрагивающая результаты сохранённого эксперимента.

Версия ниже покрывает детерминированный inventory исходников блока 1; сам generated threat-model artifact и игнорируемые runtime-каталоги в digest не входят.

Repository: local-workspace:sha256:3f081d7b9e6e7695de26323a18dff7f161facfd64f636f103b2f497e08cb2de2
Version: codex-security-snapshot/v1:sha256:677cf1a9ab0bb8f7c36ccba5ef0290a5d051c3a74af4d967857a1ec60e63e439
