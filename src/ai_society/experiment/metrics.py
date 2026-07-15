from __future__ import annotations

from collections import defaultdict

from ai_society.domain.enums import ResourceKind, StructureKind, WorldEventKind
from ai_society.domain.events import WorldEvent
from ai_society.domain.models import WorldState
from ai_society.experiment.models import (
    AgentExperimentMetrics,
    ExperimentMetrics,
    InterventionRecord,
    RecordedDecision,
)
from ai_society.simulation.engine import BUILD_COSTS


INTERACTION_KINDS = {
    WorldEventKind.MESSAGE_SENT,
    WorldEventKind.RESOURCE_TRANSFERRED,
    WorldEventKind.OFFER_CREATED,
    WorldEventKind.OFFER_ACCEPTED,
    WorldEventKind.OFFER_REJECTED,
    WorldEventKind.COMMITMENT_CREATED,
    WorldEventKind.COMMITMENT_FULFILLED,
    WorldEventKind.COMMITMENT_BROKEN,
    WorldEventKind.PROJECT_CREATED,
    WorldEventKind.PROJECT_JOINED,
    WorldEventKind.PROJECT_REFUSED,
    WorldEventKind.PROJECT_CONTRIBUTION_ADDED,
}


def build_metrics(
    *,
    state: WorldState,
    events: list[WorldEvent],
    decisions: list[RecordedDecision],
    cognition: dict[str, object],
    interventions: list[InterventionRecord],
) -> ExperimentMetrics:
    gathered: dict[str, dict[ResourceKind, int]] = defaultdict(
        lambda: defaultdict(int)
    )
    spent: dict[str, dict[ResourceKind, int]] = defaultdict(lambda: defaultdict(int))
    counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    for event in events:
        agent_id = event.actor_id
        if agent_id not in state.agents:
            continue
        if event.kind is WorldEventKind.RESOURCE_GATHERED:
            gathered[agent_id][ResourceKind(str(event.payload["resource"]))] += int(
                event.payload["amount"]
            )
        if event.kind is WorldEventKind.PROJECT_CONTRIBUTION_ADDED:
            spent[agent_id][ResourceKind(str(event.payload["resource"]))] += int(
                event.payload["amount"]
            )
        if event.kind is WorldEventKind.STRUCTURE_BUILT:
            kind = StructureKind(str(event.payload["structure"]))
            for resource, amount in BUILD_COSTS[kind].items():
                spent[agent_id][resource] += amount
        if event.kind in INTERACTION_KINDS:
            counts[agent_id]["interactions"] += 1
        if event.kind is WorldEventKind.OFFER_CREATED:
            counts[agent_id]["offers"] += 1
        if event.kind is WorldEventKind.COMMITMENT_CREATED:
            counts[agent_id]["promises_created"] += 1
        if event.kind is WorldEventKind.COMMITMENT_FULFILLED:
            counts[agent_id]["promises_fulfilled"] += 1
        if event.kind in {
            WorldEventKind.COMMITMENT_BROKEN,
            WorldEventKind.COMMITMENT_EXPIRED,
        }:
            counts[agent_id]["promises_broken"] += 1

    decision_by_agent: dict[str, list[RecordedDecision]] = defaultdict(list)
    for decision in decisions:
        decision_by_agent[decision.agent_id].append(decision)

    memories = cognition.get("memories", [])
    calls = cognition.get("model_calls", [])
    agents: list[AgentExperimentMetrics] = []
    for agent_id, agent in sorted(state.agents.items()):
        agent_decisions = decision_by_agent[agent_id]
        agent_memories = [
            row for row in memories if isinstance(row, dict) and row.get("agent_id") == agent_id
        ]
        agent_calls = [
            row for row in calls if isinstance(row, dict) and row.get("agent_id") == agent_id
        ]
        agents.append(
            AgentExperimentMetrics(
                agent_id=agent_id,
                lifespan_minutes=(
                    state.game_minute
                    if agent.body.health > 0
                    else max(
                        (item.due_minute for item in agent_decisions),
                        default=0,
                    )
                ),
                decisions=len(agent_decisions),
                successful_actions=sum(item.result.success for item in agent_decisions),
                rejected_actions=sum(not item.result.success for item in agent_decisions),
                resources_gathered=dict(gathered[agent_id]),
                resources_spent=dict(spent[agent_id]),
                buildings=sum(
                    agent_id in structure.contributor_ids
                    for structure in state.structures.values()
                ),
                interactions=counts[agent_id]["interactions"],
                offers=counts[agent_id]["offers"],
                promises_created=counts[agent_id]["promises_created"],
                promises_fulfilled=counts[agent_id]["promises_fulfilled"],
                promises_broken_or_expired=counts[agent_id]["promises_broken"],
                memory_retrievals=sum(int(row.get("access_count") or 0) for row in agent_memories),
                model_requests=len(agent_calls),
                charged_tokens=sum(int(row.get("charged_tokens") or 0) for row in agent_calls),
                latency_ms=sum(int(row.get("latency_ms") or 0) for row in agent_calls),
            )
        )

    return ExperimentMetrics(
        run_id=state.run.run_id,
        duration_minutes=state.game_minute,
        decisions=len(decisions),
        successful_actions=sum(item.result.success for item in decisions),
        rejected_actions=sum(not item.result.success for item in decisions),
        structures=len(state.structures),
        projects_completed=sum(
            project.status.value == "completed" for project in state.projects.values()
        ),
        interventions=len(interventions),
        agents=agents,
    )
