import type { AgentInspector, Catalog, LiveRun, WorldSnapshot } from "./types";

const jsonHeaders = { "Content-Type": "application/json" };

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init);
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: "Сервер недоступен" }));
    throw new Error(typeof body.detail === "string" ? body.detail : "Сервер отклонил запрос");
  }
  return response.json() as Promise<T>;
}

export const api = {
  catalog: () => request<Catalog>("/v1/observer/catalog"),
  runs: () => request<{ runs: LiveRun[] }>("/v1/runs"),
  observer: (runId: string) => request<WorldSnapshot>(`/v1/runs/${runId}/observer`),
  inspector: (runId: string, agentId: string) =>
    request<AgentInspector>(`/v1/runs/${runId}/agents/${agentId}/inspector`),
  createRun: (payload: {
    seed: number;
    width: number;
    height: number;
    agents: string[];
    provider: string;
    model: string;
    agent_provider: string;
    agent_model: string;
  }) => request<{ run_id: string; reused: boolean }>("/v1/runs", {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify(payload),
  }),
  controls: (runId: string, payload: { paused?: boolean; speed?: number }) =>
    request<WorldSnapshot>(`/v1/runs/${runId}/controls`, {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify(payload),
    }),
  spawnAgent: (runId: string, payload: {
    name: string;
    species: "human" | "wolf" | "bear" | "boar";
    provider: string;
    model: string;
    personality: string;
    behavior_description: string;
    vision_radius: number;
    x: number;
    y: number;
    health: number;
    hunger: number;
    energy: number;
  }) => request<{ agent_id: string }>(`/v1/runs/${runId}/agents`, {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify(payload),
  }),
  triggerEvent: (runId: string, payload: {
    event_type: "rain" | "cold_snap" | "heat_wave" | "fog" | "storm" | "drought" | "clear" | "resource_cache" | "berry_bloom" | "epidemic" | "meteor";
    intensity: number;
    duration_minutes: number;
    resource_kind: "wood" | "stone" | "berry" | "water";
    x?: number;
    y?: number;
  }) => request<{ event_id: string }>(`/v1/runs/${runId}/events`, {
    method: "POST",
    headers: jsonHeaders,
      body: JSON.stringify(payload),
    }),
  rebindAgent: (runId: string, agentId: string, payload: { provider: string; model: string }) =>
    request<{ agent_id: string; provider: string; model: string }>(`/v1/runs/${runId}/agents/${agentId}/model`, {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify(payload),
    }),
  save: (runId: string, name: string) =>
    request<{ name: string }>(`/v1/runs/${runId}/snapshots`, {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify({ name }),
    }),
  snapshots: () => request<{ snapshots: string[] }>("/v1/snapshots"),
  load: (name: string) =>
    request<{ run_id: string }>("/v1/runs/load", {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify({ name }),
    }),
};
