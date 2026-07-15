from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ai_society.api.observer import ObserverRunConfig, RunRegistry
from ai_society.providers.contracts import ProviderError
from ai_society.providers.ollama import OllamaModelProvider
from ai_society.providers.registry import ProviderRegistry


PROJECT_ROOT = Path(__file__).resolve().parents[3]


class CreateRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seed: int = Field(ge=0, le=2**63 - 1)
    width: int = Field(default=32, ge=8, le=128)
    height: int = Field(default=32, ge=8, le=128)
    agents: list[str] = Field(
        default_factory=lambda: ["Ада", "Борин", "Сайра"],
        min_length=1,
        max_length=10,
    )
    provider: str = Field(default="deterministic", pattern=r"^[a-z0-9_-]{1,64}$")
    model: str = Field(default="scripted-v1", pattern=r"^[A-Za-z0-9._:-]{1,128}$")


class AdvanceRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    events: int = Field(default=1, ge=1, le=10_000)


class ObserverControlRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paused: bool | None = None
    speed: int | None = Field(default=None, ge=1, le=10)

    @model_validator(mode="after")
    def requires_a_control(self) -> "ObserverControlRequest":
        if self.paused is None and self.speed is None:
            raise ValueError("at least one observer control is required")
        return self


class SnapshotRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


class LoadSnapshotRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


def build_default_provider_registry() -> ProviderRegistry:
    registry = ProviderRegistry()
    registry.register(OllamaModelProvider())
    return registry


def create_app(
    *,
    snapshot_root: Path | None = None,
    cognition_root: Path | None = None,
    provider_registry: ProviderRegistry | None = None,
    observer_tick_seconds: float = 0.35,
) -> FastAPI:
    snapshot_root = snapshot_root or PROJECT_ROOT / "data" / "snapshots"
    cognition_root = cognition_root or PROJECT_ROOT / "data" / "cognition"
    registry = RunRegistry(
        snapshot_root=snapshot_root,
        cognition_root=cognition_root,
        tick_seconds=observer_tick_seconds,
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        try:
            yield
        finally:
            await registry.shutdown()

    app = FastAPI(
        title="AI Society Simulation API",
        version="0.4.0",
        docs_url="/docs",
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.registry = registry
    app.state.provider_registry = provider_registry

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "engine": "block4"}

    @app.get("/v1/providers/{provider_id}/models")
    async def list_provider_models(provider_id: str) -> dict[str, object]:
        providers = app.state.provider_registry
        if providers is None:
            raise HTTPException(status_code=503, detail="model providers are not configured")
        try:
            models = await providers.list_models(provider_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="provider not found") from exc
        except ProviderError as exc:
            raise HTTPException(
                status_code=503,
                detail={"code": exc.code, "message": "provider is unavailable"},
            ) from exc
        return {
            "provider": provider_id,
            "models": [model.model_dump(mode="json") for model in models],
        }

    @app.get("/v1/observer/catalog")
    async def observer_catalog() -> dict[str, object]:
        """The initial observer is intentionally explicit about its safe model mode."""
        return {
            "models": [
                {
                    "provider": "deterministic",
                    "model": "scripted-experiment-v1",
                    "label": "Эксперимент: три агента, семь дней",
                    "description": "Локальный прогон с погодным кризисом и социальными эпизодами.",
                }
            ],
            "agent_names": ["Ада", "Борин", "Сайра"],
        }

    @app.post("/v1/runs", status_code=status.HTTP_201_CREATED)
    async def create_run(request: CreateRunRequest) -> dict[str, str | int]:
        try:
            engine = await registry.create(
                ObserverRunConfig(
                    seed=request.seed,
                    width=request.width,
                    height=request.height,
                    agents=request.agents,
                    provider=request.provider,
                    model=request.model,
                )
            )
            return engine.summary()
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/v1/runs/{run_id}/advance")
    async def advance_run(run_id: str, request: AdvanceRunRequest) -> dict[str, str | int]:
        try:
            await registry.advance(run_id, request.events)
            return registry.get(run_id).engine.summary()
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc

    @app.get("/v1/runs/{run_id}")
    async def read_run(run_id: str) -> dict[str, str | int]:
        try:
            return registry.get(run_id).engine.summary()
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc

    @app.get("/v1/runs/{run_id}/state")
    async def read_state(run_id: str) -> dict[str, object]:
        try:
            engine = registry.get(run_id).engine
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc
        return {
            "state": engine.state.model_dump(mode="json"),
            "event_digest": engine.event_log.digest,
        }

    @app.get("/v1/runs/{run_id}/observer")
    async def read_observer(run_id: str) -> dict[str, object]:
        try:
            return registry.snapshot(run_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc

    @app.get("/v1/runs/{run_id}/agents/{agent_id}/inspector")
    async def read_agent_inspector(run_id: str, agent_id: str) -> dict[str, object]:
        try:
            return registry.inspector(run_id, agent_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="run or agent not found") from exc

    @app.post("/v1/runs/{run_id}/controls")
    async def update_observer_controls(
        run_id: str, request: ObserverControlRequest
    ) -> dict[str, object]:
        try:
            await registry.set_controls(
                run_id, paused=request.paused, speed=request.speed
            )
            return registry.snapshot(run_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/v1/runs/{run_id}/snapshots")
    async def save_snapshot(run_id: str, request: SnapshotRequest) -> dict[str, str]:
        try:
            return {"name": registry.save_snapshot(run_id, request.name)}
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/v1/snapshots")
    async def list_snapshots() -> dict[str, list[str]]:
        return {"snapshots": registry.list_snapshots()}

    @app.post("/v1/runs/load")
    async def load_snapshot(request: LoadSnapshotRequest) -> dict[str, str | int]:
        try:
            engine = await registry.load_snapshot(request.name)
            return engine.summary()
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.websocket("/v1/runs/{run_id}/stream")
    async def stream_observer(run_id: str, websocket: WebSocket) -> None:
        try:
            queue = registry.subscribe(run_id)
            initial = registry.snapshot(run_id)
        except LookupError:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        await websocket.accept()
        await websocket.send_json({"type": "world_snapshot", "data": initial})
        try:
            while True:
                try:
                    inbound = await asyncio.wait_for(websocket.receive_text(), timeout=0.25)
                except TimeoutError:
                    inbound = None
                if inbound is not None:
                    await websocket.send_json(
                        {
                            "type": "error",
                            "code": "read_only_stream",
                            "message": "Поток наблюдения доступен только для чтения.",
                        }
                    )
                while not queue.empty():
                    await websocket.send_json(queue.get_nowait())
        except WebSocketDisconnect:
            return
        finally:
            registry.unsubscribe(run_id, queue)

    return app


app = create_app(provider_registry=build_default_provider_registry())
