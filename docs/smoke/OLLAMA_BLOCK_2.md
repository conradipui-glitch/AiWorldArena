# Ollama Block 2 Smoke

**Status:** PASS
**Validated:** 2026-07-14T23:24:17+06:00
**Ollama runtime:** 0.32.0
**Endpoint:** `http://127.0.0.1:11434`
**Model:** `gpt-oss:120b-cloud`
**Model inventory id:** `569662207105`

## Command

```powershell
.\scripts\ollama-smoke.ps1 -Model 'gpt-oss:120b-cloud' -NoStructuredOutput
```

Cloud structured-output enforcement was disabled for the transport call, while the complete JSON
Schema remained present in the trusted request envelope. The local Executive Layer still performed
strict single-object parsing and schema validation.

## Observed result

- Dynamic `GET /api/tags` inventory contained the selected model.
- One real `POST /api/chat` call completed without repair or fallback.
- The response was a valid typed intent.
- World validation rejected the requested resource action as unavailable; the simulation continued
  normally. This is the intended separation between model intention and authoritative execution.
- Requests: `1`.
- Provider-reported input/output tokens: `3245 / 325`.
- Accounted tokens: `3570`.
- Latency: `4561 ms`.
- Event digest: `c0daf5fbd934cbe0bc6895ecfddad8973b9148a738533f6c40368cab857a9959`.
- State hash: `62587599e325205139dcf613308573b365776c7904ee5329076f61081d427b3d`.

The default automated suite never invokes Ollama or the network. `/api/embed` is verified with a
bounded mock transport; a live embedding model was not installed for this chat-model smoke.
