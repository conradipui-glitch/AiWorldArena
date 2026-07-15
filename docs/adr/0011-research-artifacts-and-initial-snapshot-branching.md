# ADR-0011: Research artifacts, provenance and initial-snapshot branching

## Status

Accepted and implemented in Block 5.

## Decision

Research Layer является опциональным верхним слоем над уже проверяемым `experiment-bundle-v1`.
Он не импортируется world kernel и не получает command path к живому миру. Для каждого
catalogued bundle создаются canonical JSON `reproducibility-manifest-v1`, `research-report-v1`,
Markdown-отчёт и SVG-графики. Manifest связывает digest bundle, initial/final state, event stream,
versions engine/rules/schema, контракт мира/личности, model assignments, intervention journal и
parent provenance.

Три provenance marks являются composable:

- `clean` — baseline без вмешательств и `run.modified=false`;
- `experimental` — новый rerun или replica, где решения получаются заново;
- `modified` — explicit annotation/изменённый запуск либо child от branch snapshot.

Exact Decision Replay остаётся единственным способом воспроизвести запись без сети. Experimental
Rerun всегда создаёт новый `run_id` с `run_nonce`, а не выдаётся за replay. Минимальная replication
запускает не менее двух независимых дочерних прогонов.

Минимальный branch ограничен строго `bundle.initial_state` (игровая минута 0). Перед началом child
run initial snapshot проверяется и сохраняется в отдельном branch namespace; parent bundle остаётся
неизменным. Mid-run branch не реализуется, потому что bundle v1 не содержит атомарного снимка
world + cognition в произвольной точке. Не допускается имитировать такой контракт частичным
восстановлением памяти.

## Consequences

- Отчёты фиксируют наблюдаемые метрики и first semantic divergence, но не делают причинных
  выводов.
- Сравнение исключает provider/model diagnostics из определения behavioral divergence, чтобы
  отличие метаданных не маскировало совпадающее действие.
- Derived artifacts используют safe slugs, fixed roots, max-size checks, symlink rejection и
  atomic replace. Они проверяют внутреннюю целостность, но не подписывают внешний источник.
- Research API только возвращает catalog, manifest, report и comparison. Он не раскрывает
  cognition и не запускает models из браузера.
- Branching с изменением модели, mid-run snapshot и массовое дерево историй остаются Horizon D.
