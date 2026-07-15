export type AgentSummary = {
  id: string;
  name: string;
  position: { x: number; y: number };
  health: number;
  hunger: number;
  energy: number;
  model: string;
  goal: string;
  current_action: string;
  species: "human" | "wolf" | "bear" | "boar";
  personality: string;
  behavior_description: string;
  vision_radius: number;
};

export type WorldSnapshot = {
  run: {
    id: string;
    seed: number;
    scenario: string;
    status: "created" | "running" | "paused" | "completed";
    paused: boolean;
    speed: number;
    processed_events: number;
    modified: boolean;
  };
  environment: {
    day: number;
    clock: string;
    weather: string;
    weather_visual_only: boolean;
    night_overlay: number;
    temperature_c: number;
    crisis: boolean;
  };
  map: {
    width: number;
    height: number;
    tiles: Array<{ x: number; y: number; terrain: string }>;
    resources: Array<{ id: string; kind: string; x: number; y: number; quantity: number }>;
    structures: Array<{ id: string; kind: string; x: number; y: number }>;
  };
  agents: AgentSummary[];
  dialogues: Array<{ id: string; agent_id: string; recipient_id: string; text: string; minute: number }>;
  events: Array<{ id: string; minute: number; actor_id: string | null; kind: string; text: string }>;
  instruments: {
    population: number;
    resources: number;
    structures: number;
    active_promises: number;
  };
};

export type AgentInspector = {
  agent_id: string;
  name: string;
  model: { provider: string; name: string; tier: string };
  goal: string;
  species: "human" | "wolf" | "bear" | "boar";
  personality: string;
  behavior_description: string;
  vision_radius: number;
  body: { health: number; hunger: number; energy: number };
  position: { x: number; y: number };
  inventory: Record<string, number>;
  current_action: string;
  last_decision: string;
  observation: {
    game_minute: number;
    visible_tiles: Array<unknown>;
    visible_resources: Array<unknown>;
    visible_agents: Array<{ agent_id: string; name: string; position: { x: number; y: number }; species: string }>;
    delivered_messages: number;
  };
  known_map: Array<{ x: number; y: number }>;
  memory: Array<{ id: string; layer: string; content: string; minute: number; confidence: number }>;
  beliefs: Array<{ subject: string; statement: string; confidence: number; minute: number }>;
  relations: Array<{ agent_id: string; name: string; score: number; basis: string }>;
  active_promises: Array<{ id: string; with: string; status: string; terms: string; deadline_minute: number }>;
};

export type Catalog = {
  models: Array<{ provider: string; model: string; label: string; description: string }>;
  agent_names: string[];
  agent_models: Array<{ provider: string; model: string; label: string }>;
  creatures: Array<{ id: "human" | "wolf" | "bear" | "boar"; label: string }>;
  events: Array<{
    id: "rain" | "cold_snap" | "heat_wave" | "fog" | "storm" | "drought" | "clear" | "resource_cache" | "berry_bloom" | "epidemic" | "meteor";
    label: string;
    description: string;
  }>;
};

export type LiveRun = {
  run_id: string;
  seed: number;
  scenario: string;
  status: "created" | "running" | "paused" | "completed";
  paused: boolean;
  speed: number;
  game_minute: number;
  processed_events: number;
};
