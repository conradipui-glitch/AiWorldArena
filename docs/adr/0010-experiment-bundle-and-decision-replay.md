# ADR-0010: Experimental bundle and exact Decision Replay

## Status

Accepted for Block 4.

## Decision

Завершённый эксперимент экспортируется одним canonical JSON bundle. Он содержит исходное
состояние до инициализации engine, финальное состояние, hash-chained события, упорядоченный
поток типизированных `RecordedDecision`, cognition export, минимальные метрики и журнал
вмешательств. На bundle, cognition, финальное состояние и цепочку событий рассчитываются
отдельные проверяемые digest.

Exact replay создаёт новый авторитетный engine из `initial_state`, обрабатывает системные
события по сохранённой очереди и подставляет записанные `DecisionResolution` только при точном
совпадении sequence, minute, agent и binding revision. Provider registry, Ollama и сеть в этом
пути отсутствуют. Финальные state hash и event digest обязаны совпасть с записью.

## Consequences

- Повторный вызов LLM является Experimental Rerun, а не exact replay.
- Cognition входит в atomic export и защищён digest, но при exact replay не вычисляется заново:
  записанные решения уже являются результатом исходного cognition/retrieval.
- Bundle hashes обнаруживают повреждение и несогласованность, но не удостоверяют внешнее
  происхождение. Подписанный provenance manifest относится к Block 5.
- Branching, сравнение запусков и поиск первой точки расхождения остаются Block 5.
