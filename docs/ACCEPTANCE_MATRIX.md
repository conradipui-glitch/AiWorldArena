# Acceptance Matrix

## Блок 1

| Требование | Проверка | Статус |
|---|---|---|
| Одинаковый seed создаёт одинаковый мир | `test_same_seed_same_initial_world` | PASS |
| Другой seed изменяет мир | `test_different_seed_changes_world` | PASS |
| Scripted run детерминирован | `test_scripted_run_event_digest_is_deterministic` | PASS |
| Обрабатываются 10 000 событий | `test_ten_thousand_scheduled_events` | PASS |
| Save/load/continue эквивалентен непрерывному run | `test_save_load_continue_is_exact` | PASS |
| Hash chain обнаруживает подмену | `test_event_log_detects_tampering` | PASS |
| Snapshot не допускает traversal | `test_snapshot_name_rejects_path_traversal` | PASS |
| Tile не хранит глобальную исследованность | `test_exploration_is_agent_scoped` | PASS |
| Ядро работает без UI и LLM | `test_headless_kernel_has_no_llm_or_client_dependency` | PASS |
| 1/3/10 scripted agents не hardcoded | `test_scripted_agent_counts` | PASS |
| API создаёт и продвигает run | `test_api_create_advance_and_read` | PASS |

## Результат блока 1

- `20 passed` на Python 3.12.13.
- Coverage доменного и runtime-кода: 84% суммарно; simulation engine: 91%.
- Headless smoke: 10 000 событий, `event_digest=6b55d4e74d409687f88b2b923e77ffa8b3f3ca37471c5171c03802c1da9528ea`.
- Save → load → continue дал те же state hash и event digest, что непрерывный запуск.
- Loopback API smoke: `GET /health` вернул `status=ok`.

## Условие завершения

Все обязательные строки блока должны получить `PASS`. Известное ограничение допускается только если оно не скрывает обязательную часть и зафиксировано в этом документе.
