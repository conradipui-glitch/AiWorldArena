import type { AgentInspector, Catalog, WorldSnapshot } from "./types";

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
  }) => request<{ run_id: string }>("/v1/runs", {
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
