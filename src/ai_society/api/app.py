from pathlib import Path

from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from ai_society.simulation.engine import SimulationEngine
from ai_society.simulation.generation import generate_world
from ai_society.simulation.policies import ScriptedPolicy


class CreateRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seed: int = Field(ge=0, le=2**63 - 1)
    width: int = Field(default=32, ge=8, le=128)
    height: int = Field(default=32, ge=8, le=128)
    agents: list[str] = Field(
        default_factory=lambda: ["Ada", "Borin", "Cyra"],
        min_length=1,
        max_length=10,
    )


class AdvanceRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    events: int = Field(default=1, ge=1, le=10_000)


class RunRegistry:
    def __init__(self) -> None:
        self._runs: dict[str, SimulationEngine] = {}

    def create(self, request: CreateRunRequest) -> SimulationEngine:
        world = generate_world(
            seed=request.seed,
            width=request.width,
            height=request.height,
            agent_names=request.agents,
        )
        engine = SimulationEngine(state=world, policy=ScriptedPolicy())
        if world.run.run_id in self._runs:
            raise ValueError("an identical deterministic run already exists")
        self._runs[world.run.run_id] = engine
        return engine

    def get(self, run_id: str) -> SimulationEngine:
        try:
            return self._runs[run_id]
        except KeyError as exc:
            raise LookupError(run_id) from exc


def create_app(*, snapshot_root: Path | None = None) -> FastAPI:
    del snapshot_root  # Persistence endpoints arrive after the API contract hardens.
    app = FastAPI(
        title="AI Society Simulation API",
        version="0.1.0",
        docs_url="/docs",
        redoc_url=None,
    )
    registry = RunRegistry()
    app.state.registry = registry

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "engine": "block1"}

    @app.post("/v1/runs", status_code=status.HTTP_201_CREATED)
    def create_run(request: CreateRunRequest) -> dict[str, str | int]:
        try:
            return registry.create(request).summary()
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/v1/runs/{run_id}/advance")
    def advance_run(run_id: str, request: AdvanceRunRequest) -> dict[str, str | int]:
        try:
            engine = registry.get(run_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc
        engine.run(request.events)
        return engine.summary()

    @app.get("/v1/runs/{run_id}")
    def read_run(run_id: str) -> dict[str, str | int]:
        try:
            return registry.get(run_id).summary()
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc

    @app.get("/v1/runs/{run_id}/state")
    def read_state(run_id: str) -> dict[str, object]:
        try:
            engine = registry.get(run_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc
        return {
            "state": engine.state.model_dump(mode="json"),
            "event_digest": engine.event_log.digest,
        }

    return app


app = create_app()
