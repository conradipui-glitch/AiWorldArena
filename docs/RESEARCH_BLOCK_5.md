# Блок 5 — Research Layer + Local Checkpoint

## Статус

Research Layer завершён как локальный checkpoint. Это не публичный release candidate: по прямому
решению оператора формальный security scan и public-release audit не выполнялись и переносятся
на момент заморозки отдельного публичного выпуска.

## Назначение

Research Layer превращает завершённый семидневный experiment bundle в минимально полезный
исследовательский артефакт. Он не владеет миром и не меняет решения агентов: ядро, Executive
Layer и exact replay остаются независимыми нижними слоями.

## Состав артефакта

После `experiment` в `outputs/experiments/` остаётся исходный `experiment-bundle-v1`. Производные
файлы пишутся только под `outputs/experiments/research/`:

```text
research/
├── catalog.json
├── manifests/<name>.json
├── reports/<name>.json
├── reports/<name>.md
├── reports/<name>-charts.svg
├── comparisons/compare-<digest>.json
├── comparisons/compare-<digest>.md
└── branches/branch-<digest>.json
```

Все имена — safe slug, запись атомарна, symbolic links и выход за fixed root отклоняются. Bundle,
manifest, report и comparison содержат собственные canonical digests. Это контроль внутренней
целостности, а не криптографическая подпись происхождения.

## Версии и маркировки

Manifest фиксирует `engine_version`, `rules_version`, `world_schema_version`, seed, dimensions,
model assignments, contract initial world/personality, final hashes и parent reference.

- `clean`: исходный baseline без записанного вмешательства;
- `experimental`: rerun или replica с новыми решениями;
- `modified`: explicit annotation или branch child.

Метки могут сочетаться, если в будущем один артефакт честно обладает обоими свойствами. Они не
выражают «хорошесть» модели и не являются рейтингом.

## Три разных операции воспроизводимости

1. **World reproduction** — тот же seed/config воспроизводит физический мир и личности.
2. **Decision Replay** — `replay-experiment` заново применяет сохранённые решения, не создаёт
   provider и делает `network_calls=0`.
3. **Experimental Rerun** — `rerun-experiment` создаёт новый namespace и заново вызывает модель
   при Natural/Controlled mode. Совпадение не гарантировано и является измеряемым результатом.

## Команды

```powershell
# Baseline с необязательной явной аннотацией исследователя
.\scripts\experiment.ps1 -Mode scripted -Name baseline -Annotation 'Проверка гипотезы A'

# Проверить сохранённую запись без сети
.\scripts\research.ps1 replay-experiment baseline

# Новый прогон и обязательные две реплики
.\scripts\research.ps1 rerun-experiment baseline --name rerun-01
.\scripts\research.ps1 replicate-experiment baseline --prefix replica --count 2

# Child от проверенного начального snapshot и сравнение
.\scripts\research.ps1 branch-experiment baseline --name branch-01
.\scripts\research.ps1 compare-experiments baseline rerun-01
.\scripts\research.ps1 report-experiment baseline
.\scripts\research.ps1 catalog-experiments
```

`replicate-experiment` отклоняет `--count 1`: это защищает минимум из двух новых запусков.

## Честная граница branching

`branch-experiment` работает **только** от `bundle.initial_state` в минуте 0. Он создаёт новый
run namespace и хранит immutable parent bundle digest. Это позволяет получить полноценный
replayable child bundle без смешения event stream или cognition namespace.

Ветка из середины истории пока не поддерживается: bundle v1 не сохраняет атомарный world+cognition
snapshot на каждом decision boundary. Нельзя считать восстановление одной world state корректным
branching личности; такая функция перенесена в Horizon D.

## Отчёты и comparison

Отчёт существует в JSON для инструментов, Markdown для чтения и SVG для двух ключевых графиков:
успешные действия и собранные ресурсы по агентам. В отчёте также есть model table: provider,
model, решения, успехи/отклонения, requests, tokens и latency.

`compare-experiments` сначала проверяет совместимость world/personality contract и версий, затем
ищет первую **semantic** разницу в расписании, агенте, intent или результате действия. Provider,
model, raw rejected output и context digest не считаются расхождением поведения сами по себе.
Comparison сообщает наблюдаемую разницу, а не причинное объяснение.

## Вмешательства и API

`--annotation` записывает typed researcher annotation в immutable intervention journal и маркирует
результат `modified`. Эта MVP-аннотация не имеет скрытого пути изменения authoritative world.
Состояние мира меняется только через проверяемые public engine actions; произвольная ручная правка
мира не введена.

Research endpoints read-only по отношению к миру:

- `GET /v1/experiments`
- `GET /v1/experiments/{name}`
- `GET /v1/experiments/{name}/report`
- `GET /v1/experiments/compare?left=<name>&right=<name>`

Они не возвращают cognition export и не запускают LLM. Browser UI остаётся русскоязычным observer,
а reports служат независимым исследовательским выходом.

`GET /v1/experiments/compare` также не создаёт файлов: сохранение comparison JSON/Markdown —
явная операция CLI. Перед выдачей catalog, manifest или report сервис проверяет согласованность
catalog → manifest → verified bundle.

## Доказанные ограничения MVP

- Нет цифровой подписи, remote provenance или trusted timestamp.
- Нет branch из произвольной середины истории и нет atomic mid-run cognition snapshot.
- Нет массовых batch jobs, статистической значимости, causal graph или pattern detector.
- Scripted rerun может совпасть побитово по поведению; это не делает live LLM rerun детерминированным.
- У аннотации исследователя нет state-changing semantics; проект не имитирует ручное управление
  как emergence.
