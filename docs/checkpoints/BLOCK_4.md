# Checkpoint — Block 4: Experimental MVP

## Завершённый объём

- Сценарий «три агента, остров, семь дней» с точной границей 10 080 минут.
- Scripted, Natural и Controlled mode с проверкой model assignments.
- Авторитетные дождь, холод, кризис и последствия для тела.
- Рабочее хранилище и добровольный совместный project lifecycle с вкладами.
- Общение, transfer, offer/response, выполненное и нарушенное обещания.
- Запись каждого типизированного решения и exact replay без сети.
- Atomic world+cognition export bundle, минимальные метрики и intervention journal.
- Русскоязычный Observer запускает Block 4 scripted scenario и показывает реальную погоду.

## Приёмочный прогон

- Seed: `20260715`; карта: `48×48`; длительность: `10080` минут.
- Решений: `4761`; обработано событий планировщика: `4773`.
- Три агента завершили эксперимент с health > 0.
- State hash: `6787183ed2ecb5705af632767c414e746c59050ae8d435bfd3a5ecd3d5b9401e`.
- Event digest: `881ffd7eae17c64e3e2d1815a5e3dc6378b6fbd6fe7dfa11d260c5f989d249dd`.
- Немедленный replay: exact match, `network_calls=0`.

## Проверки checkpoint

- Full Python suite: `88 passed`; total coverage: `88%`.
- TypeScript: `npx tsc --noEmit` — passed.
- Production client: `npm run build` — passed.
- CLI export и отдельный offline replay — passed.

## Ограничения

- Полный живой семидневный Ollama run не входит в обязательный CI и зависит от выбранных моделей.
- Replication, branching, comparison/divergence и release security audit остаются Block 5.
- Bundle digests не являются цифровой подписью внешнего происхождения.

## Git policy

Checkpoint коммитится прямо в `main`, отправляется без force push и получает tag
`block-4-complete`. Commit hash и итог CI фиксируются после публикации.
