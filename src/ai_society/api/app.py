from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import (
    FastAPI,
    HTTPException,
    Response,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ai_society.api.observer import ObserverRunConfig, RunRegistry
from ai_society.domain.enums import ResourceKind
from ai_society.domain.models import Position
from ai_society.providers.contracts import ProviderError
from ai_society.providers.ollama import OllamaConfig, OllamaModelProvider
from ai_society.providers.registry import ProviderRegistry
from ai_society.research.persistence import ResearchArtifactError
from ai_society.research.service import ResearchService


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
    agent_provider: str = Field(default="deterministic", pattern=r"^[a-z0-9_-]{1,64}$")
    agent_model: str = Field(default="scripted-v1", pattern=r"^[A-Za-z0-9._:-]{1,128}$")


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


class SpawnAgentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=64)
    species: Literal["human", "wolf", "bear", "boar"] = "wolf"
    provider: str = Field(default="deterministic", pattern=r"^[a-z0-9_-]{1,64}$")
    model: str = Field(default="scripted-v1", pattern=r"^[A-Za-z0-9._:-]{1,128}$")
    personality: str = Field(min_length=1, max_length=80)
    behavior_description: str = Field(min_length=1, max_length=150)
    vision_radius: int = Field(default=3, ge=1, le=8)
    x: int = Field(ge=0, le=511)
    y: int = Field(ge=0, le=511)
    health: int = Field(default=100, ge=1, le=100)
    hunger: int = Field(default=0, ge=0, le=100)
    energy: int = Field(default=100, ge=0, le=100)


class TriggerEventRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_type: Literal[
        "rain",
        "cold_snap",
        "heat_wave",
        "fog",
        "storm",
        "drought",
        "clear",
        "resource_cache",
        "berry_bloom",
        "epidemic",
        "meteor",
    ]
    intensity: int = Field(default=30, ge=1, le=100)
    duration_minutes: int = Field(default=180, ge=0, le=7 * 24 * 60)
    resource_kind: ResourceKind = ResourceKind.BERRY
    x: int | None = Field(default=None, ge=0, le=511)
    y: int | None = Field(default=None, ge=0, le=511)

    @model_validator(mode="after")
    def resource_position_is_complete(self) -> "TriggerEventRequest":
        if self.event_type in {"resource_cache", "meteor"} and (
            self.x is None or self.y is None
        ):
            raise ValueError("this event requires a map position")
        if (self.x is None) != (self.y is None):
            raise ValueError("map position requires both coordinates")
        return self


class RebindAgentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str = Field(pattern=r"^[a-z0-9_-]{1,64}$")
    model: str = Field(pattern=r"^[A-Za-z0-9._:-]{1,128}$")


def build_default_provider_registry() -> ProviderRegistry:
    registry = ProviderRegistry()
    registry.register(
        OllamaModelProvider(OllamaConfig(include_official_cloud_catalog=True))
    )
    return registry


def create_app(
    *,
    snapshot_root: Path | None = None,
    cognition_root: Path | None = None,
    experiment_root: Path | None = None,
    provider_registry: ProviderRegistry | None = None,
    observer_tick_seconds: float = 0.35,
) -> FastAPI:
    snapshot_root = snapshot_root or PROJECT_ROOT / "data" / "snapshots"
    cognition_root = cognition_root or PROJECT_ROOT / "data" / "cognition"
    experiment_root = experiment_root or PROJECT_ROOT / "outputs" / "experiments"
    registry = RunRegistry(
        snapshot_root=snapshot_root,
        cognition_root=cognition_root,
        providers=provider_registry,
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
        version="0.5.0",
        docs_url="/docs",
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.registry = registry
    app.state.provider_registry = provider_registry
    app.state.research = ResearchService(experiment_root)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {
            "status": "ok",
            "engine": "block5",
            "observer_api": "workspace-v1",
        }

    @app.get("/v1/experiments")
    async def list_experiments() -> dict[str, object]:
        research = app.state.research
        try:
            return {
                "runs": [
                    entry.model_dump(mode="json") for entry in research.list_catalog()
                ]
            }
        except ResearchArtifactError as exc:
            raise HTTPException(
                status_code=409, detail="Каталог исследований повреждён или недоступен."
            ) from exc

    @app.get("/v1/experiments/compare")
    async def compare_experiments(left: str, right: str) -> dict[str, object]:
        try:
            return app.state.research.compare(
                left, right, persist=False
            ).model_dump(mode="json")
        except ResearchArtifactError as exc:
            status_code = 422 if "safe slug" in str(exc) else 404
            raise HTTPException(
                status_code=status_code,
                detail="Невозможно сравнить указанные исследовательские запуски.",
            ) from exc

    @app.get("/v1/experiments/{artifact_name}")
    async def read_experiment_manifest(artifact_name: str) -> dict[str, object]:
        try:
            return app.state.research.load_manifest(artifact_name).model_dump(mode="json")
        except ResearchArtifactError as exc:
            status_code = 422 if "safe slug" in str(exc) else 404
            raise HTTPException(
                status_code=status_code,
                detail="Исследовательский запуск не найден или не прошёл проверку.",
            ) from exc

    @app.get("/v1/experiments/{artifact_name}/report")
    async def read_experiment_report(artifact_name: str) -> dict[str, object]:
        try:
            return app.state.research.load_report(artifact_name).model_dump(mode="json")
        except ResearchArtifactError as exc:
            status_code = 422 if "safe slug" in str(exc) else 404
            raise HTTPException(
                status_code=status_code,
                detail="Исследовательский отчёт не найден или не прошёл проверку.",
            ) from exc

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
        agent_models = [
            {
                "provider": "deterministic",
                "model": "scripted-v1",
                "label": "Сценарное поведение (локально)",
            }
        ]
        providers = app.state.provider_registry
        if providers is not None:
            try:
                agent_models.extend(
                    {
                        "provider": item.provider,
                        "model": item.model,
                        "label": f"Ollama · {item.display_name}",
                    }
                    for item in await providers.list_models("ollama")
                )
            except (LookupError, ProviderError):
                pass
        return {
            "models": [
                {
                    "provider": "deterministic",
                    "model": "scripted-v1",
                    "label": "Свободный мир",
                    "description": (
                        "Новый процедурный мир без семидневного финала. "
                        "Выберите свой seed и наблюдайте, как он развивается."
                    ),
                },
                {
                    "provider": "deterministic",
                    "model": "scripted-experiment-v1",
                    "label": "Остров: три агента, семь дней",
                    "description": (
                        "Готовый воспроизводимый сценарий с погодным кризисом "
                        "и социальными эпизодами."
                    ),
                }
            ],
            "agent_names": ["Ада", "Борин", "Сайра"],
            "agent_models": agent_models,
            "creatures": [
                {"id": "human", "label": "Человек"},
                {"id": "wolf", "label": "Волк"},
                {"id": "bear", "label": "Медведь"},
                {"id": "boar", "label": "Кабан"},
            ],
            "events": [
                {"id": "rain", "label": "Дождь", "description": "Понижает температуру и заставляет искать тепло."},
                {"id": "cold_snap", "label": "Резкое похолодание", "description": "Опасный холод: без укрытия существа теряют здоровье."},
                {"id": "heat_wave", "label": "Жара", "description": "Ускоряет потерю энергии и меняет приоритеты выживания."},
                {"id": "fog", "label": "Туман", "description": "Временно сокращает поле зрения всех существ."},
                {"id": "storm", "label": "Шторм", "description": "Холодный ливень с ухудшением зрения и состояния."},
                {"id": "drought", "label": "Засуха", "description": "Сокращает доступные воду и ягоды, повышает температуру."},
                {"id": "clear", "label": "Ясная погода", "description": "Немедленно завершает погодный кризис."},
                {"id": "resource_cache", "label": "Запас ресурсов", "description": "Создаёт выбранный ресурс в отмеченной клетке."},
                {"id": "berry_bloom", "label": "Цветение ягод", "description": "Увеличивает запасы ягод по всей карте."},
                {"id": "epidemic", "label": "Эпидемия", "description": "Однократно снижает здоровье всех живых существ."},
                {"id": "meteor", "label": "Падение метеорита", "description": "Повреждает существ и ресурсы рядом с выбранной клеткой."},
            ],
        }

    @app.post("/v1/runs", status_code=status.HTTP_201_CREATED)
    async def create_run(
        request: CreateRunRequest, response: Response
    ) -> dict[str, str | int | bool]:
        try:
            acquisition = await registry.acquire(
                ObserverRunConfig(
                    seed=request.seed,
                    width=request.width,
                    height=request.height,
                    agents=request.agents,
                    provider=request.provider,
                    model=request.model,
                    agent_provider=request.agent_provider,
                    agent_model=request.agent_model,
                )
            )
            if acquisition.reused:
                response.status_code = status.HTTP_200_OK
            return {**acquisition.engine.summary(), "reused": acquisition.reused}
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/v1/runs")
    async def list_runs() -> dict[str, list[dict[str, str | int | bool]]]:
        """List live worlds so reopening the local app never hides one."""
        return {"runs": registry.list_runs()}

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

    @app.post("/v1/runs/{run_id}/agents", status_code=status.HTTP_201_CREATED)
    async def spawn_agent(run_id: str, request: SpawnAgentRequest) -> dict[str, str]:
        try:
            agent_id = await registry.spawn_agent(
                run_id,
                name=request.name,
                species=request.species,
                provider=request.provider,
                model=request.model,
                personality=request.personality,
                behavior_description=request.behavior_description,
                vision_radius=request.vision_radius,
                position=Position(x=request.x, y=request.y),
                health=request.health,
                hunger=request.hunger,
                energy=request.energy,
            )
            return {"agent_id": agent_id}
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="мир или модель не найдены") from exc
        except (ValueError, ProviderError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/v1/runs/{run_id}/events", status_code=status.HTTP_201_CREATED)
    async def trigger_event(run_id: str, request: TriggerEventRequest) -> dict[str, str]:
        try:
            event_id = await registry.trigger_event(
                run_id,
                event_type=request.event_type,
                intensity=request.intensity,
                duration_minutes=request.duration_minutes,
                position=(
                    Position(x=request.x, y=request.y)
                    if request.x is not None and request.y is not None
                    else None
                ),
                resource_kind=request.resource_kind,
            )
            return {"event_id": event_id}
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="мир не найден") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/v1/runs/{run_id}/agents/{agent_id}/model")
    async def rebind_agent_model(
        run_id: str, agent_id: str, request: RebindAgentRequest
    ) -> dict[str, str]:
        try:
            await registry.rebind_agent_model(
                run_id, agent_id, provider=request.provider, model=request.model
            )
            return {"agent_id": agent_id, "provider": request.provider, "model": request.model}
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="мир, персонаж или модель не найдены") from exc
        except (ValueError, ProviderError) as exc:
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
