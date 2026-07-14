# ADR-0007: Provider registry and hot-swap boundary

- **Status:** Accepted
- **Date:** 2026-07-14

## Decision

`MindBinding` хранит только server-controlled provider alias, model id, ограниченные параметры,
бюджеты и монотонную revision. Endpoint и credentials никогда не являются частью model intent,
agent prompt, world event или публичного run payload.

Ollama adapter использует `GET /api/tags`, `POST /api/chat` и `POST /api/embed`, отключает
redirects и environment proxy inheritance, ограничивает размеры/таймауты и по умолчанию
разрешает только loopback host. Fake provider не выполняет сеть.

Hot-swap валидирует provider/model inventory до изменения, увеличивает revision, сохраняет
личность и когнитивный бюджет, маркирует run как modified и записывает безопасное событие без
секретов.

## Consequences

- Новые providers подключаются через один интерфейс и registry.
- Модель не может назначить себе endpoint или расширить capability set.
- Cloud-модели доступны через локальный авторизованный Ollama runtime без нового trust boundary
  внутри simulation kernel.
