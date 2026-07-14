# ADR-0008: SQLite cognition and subjective beliefs

- **Status:** Accepted
- **Date:** 2026-07-14

## Decision

Рабочая, эпизодическая, семантическая и социальная память хранятся отдельно от объективного
`WorldState` в versioned SQLite repository, строго scoped по `run_id + agent_id`.

Retrieval использует детерминированную смесь смысловой близости, свежести, значимости,
confidence и частоты обращения. Working memory сворачивается детерминированным template
compaction; provenance исходных записей сохраняется. Confidence забытых записей и beliefs
снижается только по игровому времени.

Наблюдаемый объективный факт может породить субъективный belief, но belief никогда не становится
глобальной истиной или общей репутацией. Model-generated messages, terms и summaries остаются
помеченными как untrusted data.

## Consequences

- Замена модели не уничтожает память или beliefs личности.
- Fake embeddings делают unit tests полностью offline; Ollama embeddings подключаются тем же
  интерфейсом.
- Полный атомарный world+cognition replay bundle формируется в Block 4 вместе с Decision Replay;
  до этого world snapshot и persistent cognition store являются отдельными проверяемыми слоями.
