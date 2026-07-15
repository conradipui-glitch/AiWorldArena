# Checkpoint — Block 5: Research Layer + Local Checkpoint

**Status:** COMPLETE (local research scope)

## Завершённый объём

- Verified experiment catalog, canonical `reproducibility-manifest-v1` и provenance marks
  `clean` / `modified` / `experimental`.
- Exact Decision Replay как обязательная проверка до регистрации артефакта.
- Experimental rerun, replication не менее двух запусков и новый run namespace через `run_nonce`.
- Branch только от `bundle.initial_state` в минуте 0 с immutable parent digest; arbitrary mid-run
  cognition branch намеренно не имитируется.
- Comparison с проверкой сопоставимости и первой semantic divergence только для совместимых
  запусков; JSON/Markdown/SVG reports и model tables.
- Read-only research API: catalog, manifest, report и pure comparison без cognition export и без
  записи derived files на `GET`.
- Безопасный research persistence: fixed roots, safe slugs, size limits, symlink rejection,
  atomic replace и отказ от повторной регистрации имени до любых записей.
- `START_AIWORLD_ARENA.bat` исправлен для Windows `cmd.exe`: ASCII-wrapper, PowerShell UTF-8 BOM,
  проверка существующего observer, readiness API/UI и локальная настройка альтернативных портов.
- `scripts/test-launcher.ps1` выполняет отдельный Windows smoke на чистой паре портов; он добавлен
  в Windows CI.

## Приёмочный прогон

- Baseline: `block5-final`; seed `20260715`; `48×48`; `10080` игровых минут;
  `4761` решений; `4773` событий планировщика.
- `state_hash=1f7d401e695f6ff42396af5d9ce30f6b739cd9bfcae6d0ee0495e2ce2e6dc7aa`.
- `event_digest=881ffd7eae17c64e3e2d1815a5e3dc6378b6fbd6fe7dfa11d260c5f989d249dd`.
- Offline Decision Replay: exact match, `network_calls=0`.
- Experimental rerun, две replica, time-zero branch, comparison, report и catalog прошли через CLI.
- Launcher smoke: уже работающий observer корректно распознан; на чистых портах отдельный API,
  Vite proxy `/health` и главная страница вернули `ok/200`; тестовые процессы остановлены.

## Проверки checkpoint

- Full Python suite: `99 passed`, total coverage `87%` на Python 3.12.13. Единственное
  предупреждение — внешний `StarletteDeprecationWarning` для `TestClient`.
- `python -m compileall -q src tests`, `npx tsc --noEmit` и `npm run build` — passed.
- `scripts/test-launcher.ps1` прошёл под Windows PowerShell 5.1.
- `git diff --check` и проверка ignore rules выполняются перед публикацией.

## Ограничения и security status

- Нет signed provenance, trusted timestamp или статуса внешнего происхождения: canonical hashes
  проверяют целостность, но не заменяют подпись.
- Нет arbitrary mid-run branch, atomic cognition snapshot на каждом decision boundary, массовых
  replication jobs, statistical significance, causal graph или pattern detector.
- Это локальный research checkpoint. Формальный repository-wide security scan, deployment threat
  model и public-release audit **отложены оператором** до подготовки публичного выпуска и не
  заявляются выполненными этим checkpoint.

## Git policy

Checkpoint публикуется прямым commit в `main`, без force push и переписывания завершённой истории,
с tag `block-5-complete`. Точные commit hash, tag и результат push указываются в финальном handoff:
сам commit не может достоверно содержать собственный будущий hash.
