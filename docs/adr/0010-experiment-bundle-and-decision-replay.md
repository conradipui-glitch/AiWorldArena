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
  происхождение. Block 5 добавляет machine-checkable reproducibility manifest; цифровая подпись
  сознательно отложена, пока оператор не выберет ключевой и ownership-контракт.
- Block 5 реализует branching только от time-zero `bundle.initial_state`, сравнение запусков и
  поиск первой semantic точки расхождения. Mid-run branching остаётся последующим горизонтом,
  потому что bundle v1 не содержит атомарного cognition snapshot на decision boundary.
