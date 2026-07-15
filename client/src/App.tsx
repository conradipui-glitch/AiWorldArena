import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Brain,
  CircleNotch,
  CloudRain,
  Database,
  Eye,
  FloppyDisk,
  FolderOpen,
  Lightning,
  MapPin,
  MapTrifold,
  Pause,
  PawPrint,
  Play,
  SlidersHorizontal,
  UsersThree,
  WarningCircle,
  X,
} from "@phosphor-icons/react";
import { api } from "./api";
import { WorldCanvas } from "./components/WorldCanvas";
import type { AgentInspector, AgentSummary, Catalog, LiveRun, WorldSnapshot } from "./types";

const DEFAULT_NAMES = ["Ада", "Борин", "Сайра"];
const LAST_RUN_STORAGE_KEY = "ai-world-arena:last-run-id";
type MapPosition = { x: number; y: number };
type DirectorTab = "creature" | "event";

function meterValue(value: number, inverse = false) {
  return `${Math.max(0, Math.min(100, inverse ? 100 - value : value))}%`;
}

function gameTime(minute: number) {
  const day = Math.floor(minute / 1440) + 1;
  const hour = Math.floor((minute % 1440) / 60);
  const remainder = minute % 60;
  return `День ${day}, ${hour.toString().padStart(2, "0")}:${remainder.toString().padStart(2, "0")}`;
}

function liveRunLabel(run: LiveRun) {
  const state = run.status === "completed" ? "завершён" : run.paused ? "пауза" : "идёт";
  return `${run.scenario} · Seed ${run.seed} · ${gameTime(run.game_minute)} · ${state}`;
}

function speciesLabel(species: AgentSummary["species"]) {
  return { human: "Человек", wolf: "Волк", bear: "Медведь", boar: "Кабан" }[species] ?? "Существо";
}

function AgentCard({ agent, index, selected, onSelect }: {
  agent: AgentSummary;
  index: number;
  selected: boolean;
  onSelect: () => void;
}) {
  const scripted = agent.model.startsWith("deterministic/");
  return (
    <button className={`agent-card ${selected ? "is-selected" : ""}`} onClick={onSelect} type="button">
      <img src={`/assets/agent-${(index % 3) + 1}.png`} alt="" />
      <span className="agent-card__copy">
        <span className="agent-card__topline"><strong>{agent.name}</strong><span className="agent-card__health">{agent.health}</span></span>
        <span className="agent-card__species">{speciesLabel(agent.species)} · зрение {agent.vision_radius}</span>
        <span className="agent-card__model">{scripted ? "Сценарный агент · без LLM" : agent.model}</span>
        <span className="agent-card__action">{agent.current_action}</span>
        <span className="agent-card__open">Открыть карточку и выбрать модель</span>
        <span className="agent-card__meters">
          <span><i className="meter meter--health" style={{ width: meterValue(agent.health) }} />Зд.</span>
          <span><i className="meter meter--hunger" style={{ width: meterValue(agent.hunger, true) }} />Сыт.</span>
          <span><i className="meter meter--energy" style={{ width: meterValue(agent.energy) }} />Эн.</span>
        </span>
      </span>
    </button>
  );
}

function InspectorDrawer({ inspector, catalog, paused, onClose, onRebind }: {
  inspector: AgentInspector | null;
  catalog: Catalog | null;
  paused: boolean;
  onClose: () => void;
  onRebind: (modelKey: string) => Promise<void>;
}) {
  const llmModels = catalog?.agent_models?.filter((model) => model.provider !== "deterministic") ?? [];
  const modelChoices = llmModels.length
    ? [{ provider: "random", model: "ollama", label: "Случайная доступная Ollama-модель" }, ...llmModels]
    : [];
  const [modelKey, setModelKey] = useState("");
  const [busy, setBusy] = useState(false);
  const currentModelKey = inspector ? `${inspector.model.provider}/${inspector.model.name}` : "";
  useEffect(() => {
    const currentIsSelectable = modelChoices.some((model) => `${model.provider}/${model.model}` === currentModelKey);
    setModelKey(currentIsSelectable ? currentModelKey : modelChoices[0] ? `${modelChoices[0].provider}/${modelChoices[0].model}` : "");
  }, [currentModelKey, catalog]);
  const scripted = inspector?.model.provider === "deterministic";
  const sameModel = Boolean(modelKey && modelKey === currentModelKey);
  const modelError = inspector?.last_decision.includes("модель требует")
    || inspector?.last_decision.includes("Модель не смогла")
    || inspector?.last_decision.includes("нарушила формат")
    || inspector?.last_decision.includes("Ollama временно отклонил");

  return (
    <div className="drawer-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <aside className="detail-drawer" aria-label="Карточка персонажа">
        <header className="drawer-header">
          <div><small>КАРТОЧКА СУЩЕСТВА</small><strong>{inspector?.name ?? "Загрузка…"}</strong></div>
          <button type="button" className="icon-button" onClick={onClose} title="Закрыть"><X size={19} /></button>
        </header>
        {!inspector ? <div className="drawer-loading"><CircleNotch className="spin" size={24} /> Получаем доступные сведения…</div> : <div className="drawer-scroll">
          <section className="identity-sheet">
            <img src={`/assets/agent-${(Number(inspector.agent_id.slice(-1)) - 1) % 3 + 1}.png`} alt="" />
            <div><strong>{inspector.name}</strong><span>{speciesLabel(inspector.species)} · радиус зрения {inspector.vision_radius}</span><small>{scripted ? "Сценарное поведение — языковая модель не вызывается" : `${inspector.model.provider}/${inspector.model.name}`}</small></div>
          </section>
          <section className="intent-sheet"><Brain size={19} weight="duotone" /><div><small>ПУБЛИЧНОЕ НАМЕРЕНИЕ</small><p>{inspector.last_decision}</p></div></section>
          <section className="drawer-section"><h3>Характер и поведение</h3><p><strong>Характер:</strong> {inspector.personality}</p><p><strong>Руководство:</strong> {inspector.behavior_description}</p></section>
          <section className="drawer-section model-switcher">
            <h3>Механизм решений</h3>
            <p>{scripted ? "Сейчас действует простая проверяемая стратегия. Выберите Ollama-модель, чтобы персонаж получал контекст мира и самостоятельно выбирал намерения." : "Модель получает только то, что видит и помнит этот персонаж."}</p>
            {paused && <p className="model-state model-state--paused">Мир на паузе: модель не вызывается. После назначения нажмите ▶ в верхней панели.</p>}
            {modelError && inspector && <p className="model-state model-state--error">{inspector.last_decision}</p>}
            {modelChoices.length ? <div className="inline-control"><select aria-label="Выбрать модель персонажа" value={modelKey} onChange={(event) => setModelKey(event.target.value)}>{modelChoices.map((model) => <option key={`${model.provider}/${model.model}`} value={`${model.provider}/${model.model}`}>{model.label}</option>)}</select><button type="button" disabled={busy || !modelKey || sameModel} onClick={async () => { setBusy(true); try { await onRebind(modelKey); } finally { setBusy(false); } }}>{busy ? "Проверяем доступ…" : sameModel ? "Уже назначена" : "Проверить и назначить"}</button></div> : <p className="quiet-note">Ollama не сообщил доступных моделей. Запустите Ollama или добавьте модель — список появится после обновления страницы.</p>}
          </section>
          <div className="vitals-grid"><article><span>Здоровье</span><strong>{inspector.body.health}</strong></article><article><span>Голод</span><strong>{inspector.body.hunger}</strong></article><article><span>Энергия</span><strong>{inspector.body.energy}</strong></article></div>
          <section className="drawer-section"><h3><Eye size={15} /> Доступное восприятие</h3><p>Видит {inspector.observation.visible_tiles.length} клеток, {inspector.observation.visible_resources.length} ресурсов и {inspector.observation.visible_agents.length} существ.</p>{inspector.observation.visible_agents.length ? inspector.observation.visible_agents.map((agent) => <p key={agent.agent_id}><strong>{agent.name}</strong> · {agent.species} · клетка {agent.position.x}:{agent.position.y}</p>) : <p>Других существ в поле зрения сейчас нет.</p>}</section>
          <section className="drawer-section"><h3>Память</h3>{inspector.memory.length ? inspector.memory.slice(-5).reverse().map((memory) => <p key={memory.id}>{memory.content}</p>) : <p>Сохранённых воспоминаний пока нет.</p>}</section>
          <section className="drawer-section"><h3>Убеждения</h3>{inspector.beliefs.length ? inspector.beliefs.slice(-4).reverse().map((belief, index) => <p key={`${belief.subject}-${index}`}>{belief.statement}</p>) : <p>Устойчивые убеждения ещё не сформированы.</p>}</section>
          <section className="drawer-section"><h3>Отношения и обещания</h3>{inspector.relations.map((relation) => <p key={relation.agent_id}><strong>{relation.name}</strong> · {relation.basis}</p>)}{inspector.active_promises.map((promise) => <p key={promise.id}>Обещание с {promise.with}: {promise.terms}</p>)}{!inspector.relations.length && !inspector.active_promises.length && <p>Социальных связей пока нет.</p>}</section>
        </div>}
      </aside>
    </div>
  );
}

function DirectorDrawer({ catalog, tab, setTab, placement, setPlacement, onClose, onSpawn, onEvent, busy, onPlacementRequired }: {
  catalog: Catalog | null;
  tab: DirectorTab;
  setTab: (tab: DirectorTab) => void;
  placement: MapPosition | null;
  setPlacement: (position: MapPosition | null) => void;
  onClose: () => void;
  onSpawn: (payload: Parameters<typeof api.spawnAgent>[1]) => Promise<void>;
  onEvent: (payload: Parameters<typeof api.triggerEvent>[1]) => Promise<void>;
  busy: boolean;
  onPlacementRequired?: (required: boolean) => void;
}) {
  const [species, setSpecies] = useState<"human" | "wolf" | "bear" | "boar">("wolf");
  const [name, setName] = useState("Серый");
  const [modelKey, setModelKey] = useState("deterministic/scripted-v1");
  const [personality, setPersonality] = useState("Осторожный, территориальный");
  const [behavior, setBehavior] = useState("Исследует территорию, сближается с замеченной целью и защищается при угрозе.");
  const [vision, setVision] = useState(3);
  const [health, setHealth] = useState(100);
  const [eventType, setEventType] = useState<"rain" | "cold_snap" | "heat_wave" | "fog" | "storm" | "drought" | "clear" | "resource_cache" | "berry_bloom" | "epidemic" | "meteor">("rain");
  const [intensity, setIntensity] = useState(30);
  const [duration, setDuration] = useState(180);
  const [resource, setResource] = useState<"wood" | "stone" | "berry" | "water">("berry");
  const hasOllama = catalog?.agent_models?.some((item) => item.provider === "ollama") ?? false;
  useEffect(() => { if (hasOllama) setModelKey("random/ollama"); }, [hasOllama]);

  const selectSpecies = (next: typeof species) => {
    setSpecies(next);
    const defaults = { human: 5, wolf: 3, bear: 2, boar: 2 };
    setVision(defaults[next]);
  };
  const needsPosition = tab === "creature" || eventType === "resource_cache" || eventType === "meteor";
  const eventDescription = catalog?.events?.find((item) => item.id === eventType)?.description;
  const timedEvent = ["rain", "cold_snap", "heat_wave", "fog", "storm", "drought"].includes(eventType);
  useEffect(() => { onPlacementRequired?.(needsPosition); }, [needsPosition, onPlacementRequired]);

  return (
    <div className="drawer-backdrop drawer-backdrop--map" role="presentation">
      <aside className="detail-drawer director-drawer" aria-label="Инструменты исследователя">
        <header className="drawer-header"><div><small>ЗАФИКСИРОВАННОЕ ВМЕШАТЕЛЬСТВО</small><strong>Режиссёр мира</strong></div><button type="button" className="icon-button" onClick={onClose} title="Закрыть"><X size={19} /></button></header>
        <div className="director-tabs"><button className={tab === "creature" ? "is-active" : ""} type="button" onClick={() => { setTab("creature"); setPlacement(null); }}><PawPrint size={17} />Добавить существо</button><button className={tab === "event" ? "is-active" : ""} type="button" onClick={() => { setTab("event"); setPlacement(null); }}><Lightning size={17} />Запустить событие</button></div>
        <div className="drawer-scroll director-form">
          {tab === "creature" ? <>
            <label>Вид<select value={species} onChange={(event) => selectSpecies(event.target.value as typeof species)}>{catalog?.creatures?.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}</select></label>
            <label>Имя<input value={name} maxLength={64} onChange={(event) => setName(event.target.value)} /></label>
            <label>Модель решений<select value={modelKey} onChange={(event) => setModelKey(event.target.value)}>{hasOllama && <option value="random/ollama">Случайная доступная Ollama-модель</option>}{catalog?.agent_models?.map((item) => <option key={`${item.provider}/${item.model}`} value={`${item.provider}/${item.model}`}>{item.label}</option>)}</select></label>
            <label>Характер<input value={personality} maxLength={80} onChange={(event) => setPersonality(event.target.value)} /></label>
            <label>Описание поведения<textarea value={behavior} maxLength={150} rows={4} onChange={(event) => setBehavior(event.target.value)} /></label>
            <div className="field-pair"><label>Зрение, клеток<input type="number" min={1} max={8} value={vision} onChange={(event) => setVision(Number(event.target.value))} /></label><label>Здоровье<input type="number" min={1} max={100} value={health} onChange={(event) => setHealth(Number(event.target.value))} /></label></div>
          </> : <>
            <label>Событие<select value={eventType} onChange={(event) => { setEventType(event.target.value as typeof eventType); setPlacement(null); }}>{catalog?.events?.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}</select></label>
            {eventDescription && <p className="event-description">{eventDescription}</p>}
            {eventType === "resource_cache" && <label>Ресурс<select value={resource} onChange={(event) => setResource(event.target.value as typeof resource)}><option value="berry">Ягоды</option><option value="water">Вода</option><option value="wood">Древесина</option><option value="stone">Камень</option></select></label>}
            <div className="field-pair"><label>Интенсивность<input type="number" min={1} max={100} value={intensity} onChange={(event) => setIntensity(Number(event.target.value))} /></label><label>Длительность, мин.<input type="number" min={0} max={10080} value={duration} onChange={(event) => setDuration(Number(event.target.value))} disabled={!timedEvent} /></label></div>
          </>}
          {needsPosition && <button className={`placement-button ${placement ? "has-position" : ""}`} type="button" onClick={() => setPlacement(null)}><MapPin size={18} weight="duotone" />{placement ? `Клетка ${placement.x}:${placement.y} выбрана · выбрать другую` : "Выберите клетку на карте"}</button>}
          <p className="intervention-note">Действие изменит авторитетный мир и появится в хронике как вмешательство исследователя.</p>
          <button className="primary-action" type="button" disabled={busy || (tab === "creature" && (!name.trim() || !personality.trim() || !behavior.trim())) || (needsPosition && !placement)} onClick={() => {
            if (tab === "creature" && placement) {
              const slash = modelKey.indexOf("/");
              void onSpawn({ name, species, provider: modelKey.slice(0, slash), model: modelKey.slice(slash + 1), personality, behavior_description: behavior, vision_radius: vision, x: placement.x, y: placement.y, health, hunger: 0, energy: 100 });
            } else if (tab === "event") {
              void onEvent({ event_type: eventType, intensity, duration_minutes: duration, resource_kind: resource, ...(placement ? { x: placement.x, y: placement.y } : {}) });
            }
          }}>{busy ? <CircleNotch className="spin" size={18} /> : tab === "creature" ? <PawPrint size={18} /> : <Lightning size={18} />}{busy ? "Применяем…" : tab === "creature" ? "Добавить в мир" : "Запустить событие"}</button>
        </div>
      </aside>
    </div>
  );
}

export default function App() {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [snapshot, setSnapshot] = useState<WorldSnapshot | null>(null);
  const [inspector, setInspector] = useState<AgentInspector | null>(null);
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null);
  const [seed, setSeed] = useState("20260715");
  const [scenarioKey, setScenarioKey] = useState("deterministic/scripted-v1");
  const [initialModelKey, setInitialModelKey] = useState("deterministic/scripted-v1");
  const [connection, setConnection] = useState<"idle" | "connecting" | "live" | "offline">("idle");
  const [snapshots, setSnapshots] = useState<string[]>([]);
  const [selectedSnapshot, setSelectedSnapshot] = useState("");
  const [liveRuns, setLiveRuns] = useState<LiveRun[]>([]);
  const [selectedLiveRunId, setSelectedLiveRunId] = useState("");
  const [runsLoaded, setRunsLoaded] = useState(false);
  const [notice, setNotice] = useState("Выберите готовый сценарий или создайте отдельный мир.");
  const [busy, setBusy] = useState(false);
  const [drawer, setDrawer] = useState<"inspector" | "director" | null>(null);
  const [directorTab, setDirectorTab] = useState<DirectorTab>("creature");
  const [placement, setPlacement] = useState<MapPosition | null>(null);
  const [placementRequired, setPlacementRequired] = useState(false);
  const didRestoreLiveRun = useRef(false);

  const selectedScenario = useMemo(() => catalog?.models.find((model) => `${model.provider}/${model.model}` === scenarioKey), [catalog, scenarioKey]);
  const placementMode = drawer === "director" && placementRequired;

  const refreshLiveRuns = useCallback(async () => {
    const response = await api.runs();
    setLiveRuns(response.runs);
    setSelectedLiveRunId((current) => current && response.runs.some((run) => run.run_id === current) ? current : response.runs[0]?.run_id ?? "");
    return response.runs;
  }, []);

  const rememberRun = useCallback((runId: string) => { try { window.localStorage.setItem(LAST_RUN_STORAGE_KEY, runId); } catch { /* local storage is optional */ } }, []);

  const openExistingRun = useCallback(async (runId: string, message?: string) => {
    setBusy(true);
    try {
      const world = await api.observer(runId);
      setSnapshot(world); setSelectedAgentId(world.agents[0]?.id ?? null); setSelectedLiveRunId(runId); rememberRun(runId);
      setNotice(message ?? (world.run.status === "completed" ? "Открыт завершённый эксперимент." : world.run.paused ? "Открыт мир на паузе." : "Открыт текущий мир."));
      void refreshLiveRuns().catch(() => undefined);
    } catch (error) { setNotice(error instanceof Error ? error.message : "Не удалось открыть мир."); } finally { setBusy(false); }
  }, [refreshLiveRuns, rememberRun]);

  const createOrContinueRun = useCallback(async () => {
    if (!selectedScenario) return;
    const numericSeed = Number(seed.trim());
    if (!seed.trim() || !Number.isSafeInteger(numericSeed) || numericSeed < 0) { setNotice("Seed должен быть неотрицательным целым числом."); return; }
    const scenarioSlash = scenarioKey.indexOf("/"); const agentSlash = initialModelKey.indexOf("/");
    setBusy(true);
    try {
      const acquired = await api.createRun({ seed: numericSeed, width: 48, height: 48, agents: catalog?.agent_names ?? DEFAULT_NAMES, provider: scenarioKey.slice(0, scenarioSlash), model: scenarioKey.slice(scenarioSlash + 1), agent_provider: initialModelKey.slice(0, agentSlash), agent_model: initialModelKey.slice(agentSlash + 1) });
      const current = await api.observer(acquired.run_id);
      const world = current.run.status === "completed" ? current : await api.controls(acquired.run_id, { paused: false });
      setSnapshot(world); setSelectedAgentId(world.agents[0]?.id ?? null); setSelectedLiveRunId(acquired.run_id); rememberRun(acquired.run_id);
      setNotice(acquired.reused ? "Открыт и продолжен существующий мир." : "Мир создан: выбранные модели получили ограниченное восприятие и начали действовать.");
      void refreshLiveRuns().catch(() => undefined);
    } catch (error) { setNotice(error instanceof Error ? error.message : "Не удалось создать мир."); } finally { setBusy(false); }
  }, [catalog?.agent_names, initialModelKey, refreshLiveRuns, rememberRun, scenarioKey, seed, selectedScenario]);

  useEffect(() => {
    api.catalog().then((next) => { setCatalog(next); if (next.models[0]) setScenarioKey(`${next.models[0].provider}/${next.models[0].model}`); const hasOllama = next.agent_models?.some((model) => model.provider === "ollama"); setInitialModelKey(hasOllama ? "random/ollama" : "deterministic/scripted-v1"); }).catch((error: Error) => setNotice(error.message));
    api.snapshots().then((response) => setSnapshots(response.snapshots)).catch(() => undefined);
    api.runs().then((response) => { setLiveRuns(response.runs); setSelectedLiveRunId(response.runs[0]?.run_id ?? ""); }).catch((error: Error) => setNotice(error.message)).finally(() => setRunsLoaded(true));
  }, []);

  useEffect(() => {
    if (!runsLoaded || didRestoreLiveRun.current) return; didRestoreLiveRun.current = true; if (!liveRuns.length) return;
    let remembered: string | null = null; try { remembered = window.localStorage.getItem(LAST_RUN_STORAGE_KEY); } catch { /* optional */ }
    const candidate = liveRuns.find((run) => run.run_id === remembered) ?? (liveRuns.length === 1 ? liveRuns[0] : undefined);
    if (candidate) void openExistingRun(candidate.run_id, "Открыт активный мир с локального сервера.");
  }, [liveRuns, openExistingRun, runsLoaded]);

  const refreshInspector = useCallback(async (runId: string, agentId: string) => { try { setInspector(await api.inspector(runId, agentId)); } catch (error) { setNotice(error instanceof Error ? error.message : "Не удалось открыть карточку."); } }, []);
  useEffect(() => { if (snapshot && selectedAgentId) void refreshInspector(snapshot.run.id, selectedAgentId); }, [snapshot?.run.id, snapshot?.run.processed_events, selectedAgentId, refreshInspector]);
  useEffect(() => {
    if (!snapshot) return; setConnection("connecting"); const runId = snapshot.run.id; const protocol = location.protocol === "https:" ? "wss" : "ws"; const socket = new WebSocket(`${protocol}://${location.host}/v1/runs/${runId}/stream`);
    socket.onopen = () => setConnection("live"); socket.onerror = () => setConnection("offline"); socket.onclose = () => setConnection("offline"); socket.onmessage = (event) => { const message = JSON.parse(event.data) as { type: string; data?: WorldSnapshot }; if (message.type === "world_snapshot" && message.data) setSnapshot(message.data); };
    return () => socket.close();
  }, [snapshot?.run.id]);

  const chooseAgent = useCallback((agentId: string) => {
    setSelectedAgentId(agentId);
    setInspector(null);
    setDrawer("inspector");
    if (snapshot) void refreshInspector(snapshot.run.id, agentId);
  }, [refreshInspector, snapshot?.run.id]);
  const control = async (payload: { paused?: boolean; speed?: number }) => { if (!snapshot) return; try { setSnapshot(await api.controls(snapshot.run.id, payload)); } catch (error) { setNotice(error instanceof Error ? error.message : "Не удалось изменить время."); } };
  const saveCurrent = async () => { if (!snapshot) return; const name = `world-${snapshot.run.seed}-${snapshot.run.id.slice(-6)}-d${snapshot.environment.day}-e${snapshot.run.processed_events}-${Date.now().toString(36)}`; try { await api.save(snapshot.run.id, name); const response = await api.snapshots(); setSnapshots(response.snapshots); setSelectedSnapshot(name); setNotice(`Сохранение «${name}» создано.`); } catch (error) { setNotice(error instanceof Error ? error.message : "Не удалось сохранить мир."); } };
  const loadSelected = async () => { if (!selectedSnapshot) return; setBusy(true); try { const loaded = await api.load(selectedSnapshot); await openExistingRun(loaded.run_id, "Сохранение загружено и поставлено на паузу."); } catch (error) { setNotice(error instanceof Error ? error.message : "Не удалось загрузить сохранение."); } finally { setBusy(false); } };
  const rebind = async (key: string) => { if (!snapshot || !selectedAgentId) return; const slash = key.indexOf("/"); try { await api.rebindAgent(snapshot.run.id, selectedAgentId, { provider: key.slice(0, slash), model: key.slice(slash + 1) }); await refreshInspector(snapshot.run.id, selectedAgentId); setNotice(snapshot.run.paused ? "Модель проверена и назначена. Мир на паузе — нажмите ▶, чтобы получить её первый ход." : "Модель проверена и назначена. Она ответит на ближайшем ходу; личность и память сохранены."); } catch (error) { setNotice(error instanceof Error ? error.message : "Не удалось назначить модель."); } };
  const spawn = async (payload: Parameters<typeof api.spawnAgent>[1]) => { if (!snapshot) return; setBusy(true); try { const created = await api.spawnAgent(snapshot.run.id, payload); setPlacement(null); setSelectedAgentId(created.agent_id); setDrawer("inspector"); await refreshInspector(snapshot.run.id, created.agent_id); setNotice("Существо добавлено; вмешательство записано в хронику."); } catch (error) { setNotice(error instanceof Error ? error.message : "Не удалось добавить существо."); } finally { setBusy(false); } };
  const triggerEvent = async (payload: Parameters<typeof api.triggerEvent>[1]) => { if (!snapshot) return; setBusy(true); try { await api.triggerEvent(snapshot.run.id, payload); setPlacement(null); setNotice("Событие запущено и зафиксировано в истории мира."); } catch (error) { setNotice(error instanceof Error ? error.message : "Не удалось запустить событие."); } finally { setBusy(false); } };

  const isCompleted = snapshot?.run.status === "completed";
  return <main className="observer-shell">
    <header className="topbar">
      <div className="brand-lockup"><i className="brand-lockup__signal" /><div><strong>АРЕНА ЦИВИЛИЗАЦИЙ</strong><small>Локальная лаборатория живого мира</small></div></div>
      <div className="world-status"><span>{snapshot?.environment.weather ?? "Мир не открыт"}</span>{snapshot && <><span><CloudRain size={15} />{snapshot.environment.temperature_c} °C</span><strong>{isCompleted ? "ЭКСПЕРИМЕНТ ЗАВЕРШЁН" : `ДЕНЬ ${snapshot.environment.day}`}</strong><span>{snapshot.environment.clock}</span></>}</div>
      <div className="topbar__controls"><button type="button" className="icon-button" disabled={!snapshot || isCompleted} onClick={() => snapshot && void control({ paused: !snapshot.run.paused })} title={snapshot?.run.paused ? "Продолжить" : "Пауза"}>{snapshot?.run.paused ? <Play size={18} weight="fill" /> : <Pause size={18} weight="fill" />}</button>{[1, 3, 10].map((speed) => <button className={snapshot?.run.speed === speed ? "speed-button is-active" : "speed-button"} disabled={!snapshot || isCompleted} key={speed} type="button" onClick={() => void control({ speed })}>×{speed}</button>)}<button type="button" className="icon-button" disabled={!snapshot} onClick={() => void saveCurrent()} title="Сохранить"><FloppyDisk size={19} /></button><select className="snapshot-select" value={selectedSnapshot} onChange={(event) => setSelectedSnapshot(event.target.value)} aria-label="Выбрать сохранение"><option value="">Сохранения</option>{snapshots.map((name) => <option key={name} value={name}>{name}</option>)}</select><button type="button" className="icon-button" onClick={() => void loadSelected()} title="Загрузить" disabled={!selectedSnapshot}><FolderOpen size={19} /></button></div>
    </header>

    <aside className="agent-rail">
      <div className="section-heading"><span>ЭКСПЕРИМЕНТЫ</span><small>{liveRuns.length} активн.</small></div>
      <section className="experiment-panel"><label>Сценарий<select value={scenarioKey} onChange={(event) => setScenarioKey(event.target.value)}>{catalog?.models.map((model) => <option key={`${model.provider}/${model.model}`} value={`${model.provider}/${model.model}`}>{model.label}</option>)}</select></label><p>{selectedScenario?.description ?? "Загружаем сценарии…"}</p><label>Модель первых жителей<select value={initialModelKey} onChange={(event) => setInitialModelKey(event.target.value)}>{catalog?.agent_models?.some((model) => model.provider === "ollama") && <option value="random/ollama">Случайные Ollama-модели для каждого</option>}{catalog?.agent_models?.map((model) => <option key={`${model.provider}/${model.model}`} value={`${model.provider}/${model.model}`}>{model.label}</option>)}</select></label><label>Seed нового мира<input value={seed} onChange={(event) => setSeed(event.target.value)} inputMode="numeric" /></label><button className="experiment-panel__start" type="button" onClick={() => void createOrContinueRun()} disabled={busy || !selectedScenario}>{busy ? <CircleNotch className="spin" size={18} /> : <Play size={18} weight="fill" />}{busy ? "Подготовка…" : "Создать или открыть мир"}</button>{liveRuns.length > 0 && <div className="experiment-panel__open"><label>Открытые миры<select value={selectedLiveRunId} onChange={(event) => setSelectedLiveRunId(event.target.value)}>{liveRuns.map((run) => <option key={run.run_id} value={run.run_id}>{liveRunLabel(run)}</option>)}</select></label><button type="button" className="experiment-panel__open-button" disabled={busy || !selectedLiveRunId} onClick={() => void openExistingRun(selectedLiveRunId)}>Открыть выбранный</button></div>}</section>
      <div className="section-heading"><span>СУЩЕСТВА</span><small>{snapshot?.agents.length ?? 0}</small></div>
      <div className="agent-list">{snapshot ? snapshot.agents.map((agent, index) => <AgentCard key={agent.id} agent={agent} index={index} selected={agent.id === selectedAgentId} onSelect={() => chooseAgent(agent.id)} />) : <p className="agent-list__empty">Здесь появятся личности выбранного мира.</p>}</div>
      <div className={`connection connection--${snapshot ? connection : "idle"}`}><span />{snapshot ? (connection === "live" ? "Поток подключён" : connection === "connecting" ? "Подключение…" : "Поток отключён") : "Мир ещё не открыт"}</div>
    </aside>

    <section className="map-panel"><div className="map-panel__heading"><span>КАРТА МИРА</span><small>{snapshot ? `Seed ${snapshot.run.seed} · ${snapshot.map.width} × ${snapshot.map.height}` : "Выберите сценарий слева"}</small><span className="map-panel__legend">Колесо — масштаб · перетаскивание — обзор</span></div>{snapshot ? <WorldCanvas world={snapshot} selectedAgentId={selectedAgentId} onSelectAgent={chooseAgent} placementMode={placementMode} placement={placement} onMapPosition={setPlacement} /> : <div className="world-empty"><MapTrifold size={36} weight="duotone" /><strong>Мир ждёт запуска</strong><p>Выберите сценарий и механизм решений первых жителей.</p></div>}<div className="map-panel__footer"><span><i className="legend-swatch legend-swatch--grass" />суша</span><span><i className="legend-swatch legend-swatch--water" />вода</span><span><i className="legend-swatch legend-swatch--forest" />лес</span><span><i className="legend-swatch legend-swatch--rock" />камень</span><small>{snapshot?.run.modified ? "История содержит явно зафиксированные вмешательства." : "Мир развивается без скрытых изменений исследователя."}</small></div></section>

    <aside className="chronicle-rail"><div className="chronicle-clock"><small>ВРЕМЯ МИРА</small><strong>{snapshot?.environment.clock ?? "—"}</strong><span>{snapshot ? `День ${snapshot.environment.day}` : "Мир не запущен"}</span></div><div className="section-heading"><span>ХРОНИКА</span><small>{snapshot?.events.length ?? 0}</small></div><ol className="event-list">{snapshot ? [...snapshot.events].reverse().map((event) => <li className={event.kind.includes("researcher") || event.kind === "agent_spawned" ? "is-intervention" : ""} key={event.id}><time>{gameTime(event.minute).replace("День ", "Д")}</time><span>{event.text}</span></li>) : <li className="event-list__empty"><span>Здесь появятся решения, разговоры и события мира.</span></li>}</ol><div className="instrument-panel"><div className="section-heading"><span>ИНСТРУМЕНТЫ</span></div><p><UsersThree size={16} />Население <strong>{snapshot?.instruments.population ?? "—"}</strong></p><p><Database size={16} />Ресурсы <strong>{snapshot?.instruments.resources ?? "—"}</strong></p><p><WarningCircle size={16} />Обещания <strong>{snapshot?.instruments.active_promises ?? "—"}</strong></p><button type="button" disabled={!snapshot || isCompleted} onClick={() => { setPlacement(null); setDrawer("director"); }}><SlidersHorizontal size={17} />Открыть режиссёр мира</button></div></aside>

    <footer className="observer-footer"><span aria-live="polite">{notice}</span><small>{snapshot ? "Кликните по существу, чтобы открыть его восприятие, память и модель." : "Готовый сценарий — это выбор, а не обязательный режим."}</small></footer>
    {drawer === "inspector" && <InspectorDrawer inspector={inspector} catalog={catalog} paused={snapshot?.run.paused ?? true} onClose={() => setDrawer(null)} onRebind={rebind} />}
    {drawer === "director" && <DirectorDrawer catalog={catalog} tab={directorTab} setTab={setDirectorTab} placement={placement} setPlacement={setPlacement} onPlacementRequired={setPlacementRequired} onClose={() => { setDrawer(null); setPlacement(null); setPlacementRequired(false); }} onSpawn={spawn} onEvent={triggerEvent} busy={busy} />}
  </main>;
}
