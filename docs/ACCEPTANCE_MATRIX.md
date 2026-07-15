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

## Блок 2

| Требование | Проверка | Статус |
|---|---|---|
| Executive Layer изолирует provider I/O от world kernel | `test_invalid_json_gets_exactly_one_repair_and_valid_repair_executes` | PASS |
| Повторно невалидный или глубоко вложенный ответ безопасно превращается в `wait` | `test_second_invalid_response_falls_back_and_simulation_continues`; `test_excessively_nested_model_json_falls_back_and_closes_budget_calls` | PASS |
| Prompt не раскрывает hidden world или чужую память | `test_prompt_context_excludes_hidden_world_and_every_foreign_memory_layer` | PASS |
| Ошибка и отмена provider call закрывают budget reservation | `test_unexpected_provider_error_finalizes_reservation_and_falls_back`; `test_cancelled_provider_call_finalizes_reservation_and_reraises` | PASS |
| Fake provider детерминирован и не вызывает сеть; inventory динамический | `test_fake_provider_is_deterministic_and_never_opens_network`; `test_api_lists_dynamic_provider_inventory_without_accepting_endpoint` | PASS |
| Ollama transport ограничен, а malformed embeddings нормализуются | `test_ollama_total_deadline_stops_a_slow_drip_response`; `test_ollama_embedding_overflow_is_a_typed_provider_error` | PASS |
| Cognitive accounting учитывает запросы, токены, latency и ошибки | `test_cognitive_budget_reservation_is_atomic_and_failed_calls_are_charged`; `test_cognitive_budget_reserves_estimated_tokens_not_utf8_bytes` | PASS |
| Hot-swap сохраняет личность/память/beliefs и отбрасывает поздний ответ | `test_hot_swap_discards_late_old_model_response_and_preserves_personality` | PASS |
| Два runner не применяют один decision step параллельно | `test_concurrent_runners_serialize_one_decision_step_per_run` | PASS |
| Четыре слоя памяти изолированы по run и agent | `test_four_memory_layers_round_trip_and_are_agent_scoped` | PASS |
| Compaction, retrieval и forgetting детерминированы по игровому времени | `test_working_memory_compacts_deterministically_with_provenance`; `test_forgetting_is_monotonic_and_idempotent_for_same_minute` | PASS |
| Semantic memory доступна через end-to-end projector | `test_projector_creates_retrievable_semantic_memory_end_to_end` | PASS |
| Результат действия записывается в working memory | `test_runner_records_action_outcome_in_agent_working_memory` | PASS |
| Beliefs остаются субъективными, наблюдение может заменить противоречивое belief | `test_beliefs_are_subjective_and_do_not_become_global_reputation`; `test_direct_observation_supersedes_contradictory_current_beliefs` | PASS |
| `build_fire` и `build_shelter` проходят authoritative validation | `test_fire_building_uses_world_validation_and_resources`; `test_shelter_building_uses_world_validation_and_resources` | PASS |
| Messages доставляются/истекают асинхронно и идемпотентно | `test_message_is_sent_then_delivered_asynchronously_and_expiry_is_idempotent` | PASS |
| Transfer и accepted offer не допускают частичной мутации | `test_transfer_is_atomic_and_requires_inventory_and_proximity`; `test_offer_acceptance_revalidates_inventory_without_partial_mutation` | PASS |
| Commitment lifecycle и pending deadlines переживают snapshot | `test_direct_promise_expires_once_at_authoritative_deadline`; `test_pending_commitment_deadline_survives_snapshot` | PASS |
| Snapshot отклоняет неизвестную schema и dangling world references | `test_snapshot_rejects_unknown_schema_version`; `test_snapshot_rejects_self_consistent_but_dangling_world_references` | PASS |
| CLI resume помечает snapshot как непроверенный импорт | `test_cli_resume_marks_snapshot_as_unverified_import` | PASS |
| Изолированный реальный Ollama chat проходит через тот же Executive Layer | `docs/smoke/OLLAMA_BLOCK_2.md` | PASS — ISOLATED SMOKE 2026-07-14 |

## Результат блока 2

- Full suite: `81 passed` на Python 3.12.13.
- Coverage: 88% (`2351` statements, `275` missed).
- Headless smoke: 10 000 событий; `state_hash=3889e8b9a8c4617bb095e43c93bce8d3772004a74a49c1cb1d5339397b67284a`, `event_digest=7f87242f5dd2500d5d5bbc8d28493a4f10604bc5a91a199c05c5196c8ca1f7e4`.
- Git checkpoint: commit hash и результат GitHub Actions фиксируются в итоговой передаче; tag — `block-2-complete`.
- Формальный security scan намеренно отложен; промежуточный scan не был запечатан после изменения
  target snapshot, поэтому финального отчёта Block 2 нет.

## Блок 3

| Требование | Проверка | Статус |
|---|---|---|
| Phaser отображает server-projected tiles, ресурсы, постройки и агентов | Browser smoke + `client/src/components/WorldCanvas.tsx` | PASS |
| Камера и визуальные переходы действий не меняют серверный мир | Browser smoke; Phaser pan + move tween, authoritative positions приходят из snapshot | PASS |
| День/ночь и базовая погода видны как чистая presentation-проекция | `test_observer_projection_controls_inspector_and_snapshot` | PASS |
| Клиент получает русскоязычный live snapshot и может переподключиться | `test_read_only_websocket_reconnects_with_fresh_snapshot` | PASS |
| Поток не принимает мутацию от клиента | `test_read_only_websocket_reconnects_with_fresh_snapshot` | PASS |
| Browser не может передать авторитетный `state` в control endpoint | `test_observer_projection_controls_inspector_and_snapshot` | PASS |
| Headless world продолжается без браузера | `test_headless_run_continues_after_control_without_browser` | PASS |
| Pause, ×1/×3/×10, save/load реализованы через narrow operator API | `test_observer_projection_controls_inspector_and_snapshot` + browser smoke | PASS |
| Inspector показывает agent-scoped observation, known map, SQLite memory, beliefs, relations, promises и последнее решение | `test_observer_projection_controls_inspector_and_snapshot` + browser smoke | PASS |
| Клиент типизируется и собирается на Windows | `npx tsc --noEmit`; `npm run build` | PASS |
| Локальный запуск описан и работает на loopback | `docs/OBSERVER_BLOCK_3.md`; `scripts/observer.ps1`; browser smoke | PASS |

## Результат блока 3

- Full Python suite: `84 passed` на Python 3.12.13; coverage: `88%`.
- Client: `npx tsc --noEmit` и `npm run build` проходят.
- Browser smoke: создание запуска, WebSocket-подключение, пауза/скорость, хроника и
  инспектор агента проверены в локальном браузере без console errors.
- Визуальная QA: `design-qa.md`, итог `passed`.
- Ограничение: единственный доступный выбор модели в текущем Visual Observer —
  воспроизводимый `scripted-v1`; подстановка произвольной Ollama-модели в экран
  требует отдельной связки с `ExecutiveRunner` и не имитируется UI.

## Блок 4

| Требование | Проверка | Статус |
|---|---|---|
| Три агента с одинаковыми стартовыми ресурсами автономно живут ровно семь дней | `test_seven_day_experiment_exports_metrics_and_replays_exactly` | PASS |
| Все три агента воспринимают, решают, действуют и сохраняют субъективную карту | `test_seven_day_experiment_exports_metrics_and_replays_exactly` | PASS |
| Scripted, Natural и Controlled mode имеют явные сравнимые контракты | `test_experiment_modes_enforce_comparable_model_assignments` | PASS |
| Повторно невалидный model output не останавливает Controlled experiment | `test_controlled_mode_survives_invalid_model_output` | PASS |
| Дождь и кризисное похолодание являются авторитетными событиями | `test_seven_day_experiment_exports_metrics_and_replays_exactly` | PASS |
| Совместный проект поддерживает join/refuse, раздельные вклады и завершение | `test_seven_day_experiment_exports_metrics_and_replays_exactly` | PASS |
| Простое хранилище реально принимает и возвращает ресурсы | `test_seven_day_experiment_exports_metrics_and_replays_exactly` | PASS |
| Общение, transfer, offer/accept, выполненное и нарушенное обещания наблюдаемы | `test_seven_day_experiment_exports_metrics_and_replays_exactly` | PASS |
| Atomic bundle содержит world, cognition, decisions, events, metrics и interventions | `test_seven_day_experiment_exports_metrics_and_replays_exactly` | PASS |
| Exact Decision Replay совпадает по state hash и event digest без provider/network | `test_seven_day_experiment_exports_metrics_and_replays_exactly`; CLI acceptance | PASS |
| Русскоязычный Observer показывает сценарий и авторитетную погоду | `test_observer_exposes_authoritative_block4_experiment_in_russian` | PASS |
| CLI запускает эксперимент, экспортирует данные и отдельно проверяет replay | `scripts/experiment.ps1`; CLI acceptance | PASS |

## Результат блока 4

- Acceptance run: seed `20260715`, `48×48`, `10080` минут, `4761` решений.
- Все три агента живы; один совместный проект завершён; intervention journal пуст и явен.
- `state_hash=6787183ed2ecb5705af632767c414e746c59050ae8d435bfd3a5ecd3d5b9401e`.
- `event_digest=881ffd7eae17c64e3e2d1815a5e3dc6378b6fbd6fe7dfa11d260c5f989d249dd`.
- Exact replay повторно подтверждён с `network_calls=0`.
- Full Python suite: `88 passed`; total coverage: `88%`.
- Client: `npx tsc --noEmit` и `npm run build` проходят.

## Блок 5

| Требование | Проверка | Статус |
|---|---|---|
| Baseline получает каталог, manifest, JSON/Markdown/SVG report и `clean` mark | `test_catalog_manifest_report_and_clean_mark_are_verified` | PASS |
| Повторное имя не может перезаписать уже зарегистрированный bundle, manifest или catalog | `test_duplicate_artifact_name_is_rejected_before_any_registered_data_changes` | PASS |
| Явная аннотация записывается в intervention journal и маркирует run `modified` | `test_explicit_annotation_is_journaled_and_marks_run_modified` | PASS |
| Rerun создаёт новый namespace, сохраняет world/personality contract и получает `experimental` mark | `test_experimental_rerun_has_a_new_namespace_and_explicit_mark`; CLI acceptance | PASS |
| Replication не допускает меньше двух новых запусков | `test_research_cli_reads_artifacts_and_rejects_nonminimal_replication`; CLI acceptance с `--count 2` | PASS |
| Branch только из time-zero snapshot сохраняет parent contract и независимый namespace | `test_initial_snapshot_branch_preserves_parent_contract_and_namespace`; CLI acceptance | PASS |
| Сравнение находит первую semantic разницу только у сопоставимых запусков | `test_comparison_finds_first_semantic_behavior_divergence`; `test_incomparable_runs_do_not_claim_a_first_behavioral_divergence` | PASS |
| Research API выдаёт только metadata, не раскрывает cognition и не пишет comparison на GET | `test_research_api_exposes_metadata_not_cognition` | PASS |
| API отклоняет manifest/report/catalog при пропавшем или invalid catalogued bundle | `test_research_api_rejects_metadata_for_a_missing_catalogued_bundle` | PASS |
| CLI читает catalog/report и регенерирует derived report | `test_research_cli_reads_artifacts_and_rejects_nonminimal_replication` | PASS |
| Windows launcher корректно поднимает новую пару API/UI, proxy и главную страницу на чистых портах | `scripts/test-launcher.ps1`; ручной Windows smoke | PASS |
| Формальный repository-wide security scan и public-release audit | Явно отложены оператором до подготовки публичного выпуска | DEFERRED BY OPERATOR |

## Результат блока 5

- Acceptance baseline: `block5-final`, seed `20260715`, `48×48`, `10080` минут,
  `4761` решений и `4773` событий планировщика.
- `state_hash=1f7d401e695f6ff42396af5d9ce30f6b739cd9bfcae6d0ee0495e2ce2e6dc7aa`;
  `event_digest=881ffd7eae17c64e3e2d1815a5e3dc6378b6fbd6fe7dfa11d260c5f989d249dd`.
- Decision Replay baseline прошёл без сети; rerun, две replica, time-zero branch, comparison,
  catalog и report прошли отдельный CLI acceptance.
- `START_AIWORLD_ARENA.bat` проверен под Windows PowerShell на уже запущенном observer и на
  чистой паре портов: API `/health`, UI proxy `/health` и главная страница вернули `ok/200`.
- Full Python suite: `99 passed`, total coverage `87%` на Python 3.12.13; один известный
  `StarletteDeprecationWarning` относится к внешнему `TestClient` dependency.
- `python -m compileall -q src tests`, `npx tsc --noEmit` и `npm run build` проходят.
- Это локальный research checkpoint, а не публичный release candidate: формальный security audit
  в этот блок не включён по прямому решению оператора.

## Условие завершения

Все обязательные строки текущего локального scope должны получить `PASS`. Явно отложенная
public-release проверка не считается выполненной и не позволяет заявлять security certification.
Известное ограничение допускается только если оно не скрывает обязательную часть и зафиксировано
в этом документе.
