# ADR-0001: Python world kernel and TypeScript visual client

- **Status:** Accepted
- **Date:** 2026-07-14

## Decision

Авторитетный мир, Executive Layer, persistence и analytics реализуются на Python 3.12. Будущий визуальный клиент использует TypeScript, Phaser и Vite. Связь проходит через REST/WebSocket contracts.

## Consequences

Headless-тесты не зависят от браузера. Клиент невозможно случайно превратить в источник истины. Появляются два dependency toolchain, которые должны иметь lock-файлы.
