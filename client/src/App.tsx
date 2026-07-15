import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  CircleNotch,
  CloudRain,
  Database,
  FloppyDisk,
  FolderOpen,
  MapTrifold,
  Pause,
  Play,
  UsersThree,
  WarningCircle,
} from "@phosphor-icons/react";
import { api } from "./api";
import { WorldCanvas } from "./components/WorldCanvas";
import type { AgentInspector, AgentSummary, Catalog, LiveRun, WorldSnapshot } from "./types";

const DEFAULT_NAMES = ["Ада", "Борин", "Сайра"];
const LAST_RUN_STORAGE_KEY = "ai-world-arena:last-run-id";

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

function AgentCard({
  agent,
  index,
  selected,
  onSelect,
}: {
  agent: AgentSummary;
  index: number;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <button className={`agent-card ${selected ? "is-selected" : ""}`} onClick={onSelect} type="button">
      <img src={`/assets/agent-${(index % 3) + 1}.png`} alt="" />
      <span className="agent-card__copy">
        <span className="agent-card__topline">
          <strong>{agent.name}</strong>
          <span className="agent-card__health">{agent.health}</span>
        </span>
        <span className="agent-card__model">{agent.model}</span>
        <span className="agent-card__action">{agent.current_action}</span>
        <span className="agent-card__meters">
          <span><i className="meter meter--health" style={{ width: meterValue(agent.health) }} />Зд.</span>
          <span><i className="meter meter--hunger" style={{ width: meterValue(agent.hunger, true) }} />Сыт.</span>
          <span><i className="meter meter--energy" style={{ width: meterValue(agent.energy) }} />Эн.</span>
        </span>
      </span>
    </button>
  );
}

function Inspector({ inspector }: { inspector: AgentInspector | null }) {
  if (!inspector) {
    return (
      <section className="inspector inspector--empty">
        <MapTrifold size={28} weight="duotone" />
        <p>Выберите агента, чтобы открыть его доступное знание о мире.</p>
      </section>
    );
  }
  return (
    <section className="inspector">
      <div className="section-heading">
        <span>ИНСПЕКТОР</span>
        <small>{inspector.name}</small>
      </div>
      <div className="inspector__identity">
        <img src={`/assets/agent-${(Number(inspector.agent_id.slice(-1)) - 1) % 3 + 1}.png`} alt="" />
        <div>
          <strong>{inspector.name}</strong>
          <span>{inspector.current_action}</span>
          <small>Модель: {inspector.model.name}</small>
        </div>
      </div>
      <p className="inspector__decision">{inspector.last_decision}</p>
      <div className="inspector__grid">
        <article>
          <h3>Наблюдение</h3>
          <p>Видит клеток: {inspector.observation.visible_tiles.length}</p>
          <p>Ресурсов рядом: {inspector.observation.visible_resources.length}</p>
          <p>Известная карта: {inspector.known_map.length}</p>
        </article>
        <article>
          <h3>Память</h3>
          {inspector.memory.length ? inspector.memory.slice(-3).reverse().map((memory) => (
            <p key={memory.id}>{memory.content}</p>
          )) : <p>Пока нет сохранённых воспоминаний.</p>}
        </article>
        <article>
          <h3>Убеждения</h3>
          {inspector.beliefs.length ? inspector.beliefs.slice(-3).reverse().map((belief, index) => (
            <p key={`${belief.subject}-${index}`}>{belief.statement}</p>
          )) : <p>Наблюдения ещё не сформировали устойчивых убеждений.</p>}
        </article>
        <article>
          <h3>Отношения</h3>
          {inspector.relations.length ? inspector.relations.map((relation) => (
            <p key={relation.agent_id}><strong>{relation.name}</strong> · {relation.basis}</p>
          )) : <p>Других агентов нет.</p>}
        </article>
        <article className="inspector__promise">
          <h3>Активные обещания</h3>
          {inspector.active_promises.length ? inspector.active_promises.map((promise) => (
            <p key={promise.id}>С {promise.with}: {promise.terms}</p>
          )) : <p>Нет активных обещаний.</p>}
        </article>
      </div>
    </section>
  );
}

export default function App() {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [snapshot, setSnapshot] = useState<WorldSnapshot | null>(null);
  const [inspector, setInspector] = useState<AgentInspector | null>(null);
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null);
  const [seed, setSeed] = useState("20260715");
  const [modelKey, setModelKey] = useState("deterministic/scripted-v1");
  const [connection, setConnection] = useState<"idle" | "connecting" | "live" | "offline">("idle");
  const [snapshots, setSnapshots] = useState<string[]>([]);
  const [selectedSnapshot, setSelectedSnapshot] = useState("");
  const [liveRuns, setLiveRuns] = useState<LiveRun[]>([]);
  const [selectedLiveRunId, setSelectedLiveRunId] = useState("");
  const [runsLoaded, setRunsLoaded] = useState(false);
  const [notice, setNotice] = useState("Выберите готовый сценарий или создайте отдельный мир.");
  const [busy, setBusy] = useState(false);
  const didRestoreLiveRun = useRef(false);

  const selectedModel = useMemo(() => catalog?.models.find(
    (model) => `${model.provider}/${model.model}` === modelKey,
  ), [catalog, modelKey]);

  const refreshLiveRuns = useCallback(async () => {
    const response = await api.runs();
    setLiveRuns(response.runs);
    setSelectedLiveRunId((current) => (
      current && response.runs.some((run) => run.run_id === current)
        ? current
        : response.runs[0]?.run_id ?? ""
    ));
    return response.runs;
  }, []);

  const rememberRun = useCallback((runId: string) => {
    try {
      window.localStorage.setItem(LAST_RUN_STORAGE_KEY, runId);
    } catch {
      // The observer remains usable when browser storage is unavailable.
    }
  }, []);

  const openExistingRun = useCallback(async (
    runId: string,
    { resume = false, message }: { resume?: boolean; message?: string } = {},
  ) => {
    setBusy(true);
    try {
      const current = await api.observer(runId);
      const world = resume && current.run.status !== "completed"
        ? await api.controls(runId, { paused: false })
        : current;
      setSnapshot(world);
      setSelectedAgentId(world.agents[0]?.id ?? null);
      setSelectedLiveRunId(runId);
      rememberRun(runId);
      setNotice(message ?? (
        world.run.status === "completed"
          ? "Открыт завершённый эксперимент. Его карта, хроника и сохранения доступны для изучения."
          : world.run.paused
          ? "Открыт мир на паузе. Нажмите ▶, когда будете готовы продолжить время."
          : "Открыт текущий мир: симуляция продолжает работать на локальном сервере."
      ));
      void refreshLiveRuns().catch(() => undefined);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Не удалось открыть выбранный мир.");
    } finally {
      setBusy(false);
    }
  }, [refreshLiveRuns, rememberRun]);

  const createOrContinueRun = useCallback(async () => {
    if (!selectedModel) return;
    const normalizedSeed = seed.trim();
    if (!normalizedSeed) {
      setNotice("Введите seed нового мира.");
      return;
    }
    const numericSeed = Number(normalizedSeed);
    if (!Number.isSafeInteger(numericSeed) || numericSeed < 0) {
      setNotice("Seed должен быть неотрицательным целым числом.");
      return;
    }
    setBusy(true);
    try {
      const acquired = await api.createRun({
        seed: numericSeed,
        width: 48,
        height: 48,
        agents: catalog?.agent_names ?? DEFAULT_NAMES,
        provider: selectedModel.provider,
        model: selectedModel.model,
      });
      const current = await api.observer(acquired.run_id);
      const world = current.run.status === "completed"
        ? current
        : await api.controls(acquired.run_id, { paused: false });
      setSnapshot(world);
      setSelectedAgentId(world.agents[0]?.id ?? null);
      setSelectedLiveRunId(acquired.run_id);
      rememberRun(acquired.run_id);
      setNotice(
        world.run.status === "completed"
          ? "Этот готовый эксперимент уже завершён. Открыта его итоговая хроника."
          : acquired.reused
          ? "Открыт и продолжен существующий мир. Его прежняя история сохранена."
          : "Мир создан и запущен: агенты принимают решения, а хроника фиксирует последствия.",
      );
      void refreshLiveRuns().catch(() => undefined);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Не удалось создать мир.");
    } finally {
      setBusy(false);
    }
  }, [catalog?.agent_names, refreshLiveRuns, rememberRun, seed, selectedModel]);

  useEffect(() => {
    api.catalog()
      .then((nextCatalog) => {
        setCatalog(nextCatalog);
        if (nextCatalog.models[0]) setModelKey(`${nextCatalog.models[0].provider}/${nextCatalog.models[0].model}`);
      })
      .catch((error: Error) => setNotice(error.message));
    api.snapshots().then((response) => setSnapshots(response.snapshots)).catch(() => undefined);
    api.runs()
      .then((response) => {
        setLiveRuns(response.runs);
        setSelectedLiveRunId(response.runs[0]?.run_id ?? "");
      })
      .catch((error: Error) => setNotice(error.message))
      .finally(() => setRunsLoaded(true));
  }, []);

  useEffect(() => {
    if (!runsLoaded || didRestoreLiveRun.current) return;
    didRestoreLiveRun.current = true;
    if (!liveRuns.length) return;
    let rememberedRunId: string | null = null;
    try {
      rememberedRunId = window.localStorage.getItem(LAST_RUN_STORAGE_KEY);
    } catch {
      // With no storage, reopening the only active local world is still intuitive.
    }
    const candidate = liveRuns.find((run) => run.run_id === rememberedRunId)
      ?? (liveRuns.length === 1 ? liveRuns[0] : undefined);
    if (candidate) {
      void openExistingRun(candidate.run_id, {
        message: "Открыт активный мир с локального сервера.",
      });
    }
  }, [liveRuns, openExistingRun, runsLoaded]);

  const refreshInspector = useCallback(async (runId: string, agentId: string) => {
    try {
      setInspector(await api.inspector(runId, agentId));
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Не удалось открыть инспектор.");
    }
  }, []);

  useEffect(() => {
    if (!snapshot || !selectedAgentId) return;
    void refreshInspector(snapshot.run.id, selectedAgentId);
  }, [snapshot?.run.id, snapshot?.run.processed_events, selectedAgentId, refreshInspector]);

  useEffect(() => {
    if (!snapshot) return;
    setConnection("connecting");
    const apiOrigin = import.meta.env.VITE_API_ORIGIN
      ?? (window.location.port === "5173"
        ? `${window.location.protocol}//${window.location.hostname}:8000`
        : window.location.origin);
    const socketOrigin = apiOrigin.replace(/^http/, "ws");
    const socket = new WebSocket(`${socketOrigin}/v1/runs/${snapshot.run.id}/stream`);
    socket.onopen = () => setConnection("live");
    socket.onmessage = (event) => {
      const message = JSON.parse(event.data) as { type: string; data?: WorldSnapshot; message?: string };
      if (message.type === "world_snapshot" && message.data) setSnapshot(message.data);
      if (message.type === "error" && message.message) setNotice(message.message);
    };
    socket.onerror = () => setConnection("offline");
    socket.onclose = () => setConnection((current) => current === "live" ? "offline" : current);
    return () => socket.close();
  }, [snapshot?.run.id]);

  async function control(payload: { paused?: boolean; speed?: number }) {
    if (!snapshot) return;
    try {
      setSnapshot(await api.controls(snapshot.run.id, payload));
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Не удалось применить управление.");
    }
  }

  async function saveCurrent() {
    if (!snapshot) return;
    try {
      const runKey = snapshot.run.id.replace(/^run-/, "");
      const uniqueSuffix = Date.now().toString(36);
      const name = `world-${snapshot.run.seed}-${runKey}-d${snapshot.environment.day}-e${snapshot.run.processed_events}-${uniqueSuffix}`;
      const saved = await api.save(snapshot.run.id, name);
      const response = await api.snapshots();
      setSnapshots(response.snapshots);
      setSelectedSnapshot(saved.name);
      setNotice(`Сохранение «${saved.name}» готово.`);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Не удалось сохранить запуск.");
    }
  }

  async function loadSelected() {
    if (!selectedSnapshot) return;
    try {
      const loaded = await api.load(selectedSnapshot);
      const world = await api.observer(loaded.run_id);
      setSnapshot(world);
      setSelectedAgentId(world.agents[0]?.id ?? null);
      setSelectedLiveRunId(loaded.run_id);
      rememberRun(loaded.run_id);
      setNotice(
        world.run.status === "completed"
          ? `Загружен завершённый эксперимент «${selectedSnapshot}».`
          : `Загружено сохранение «${selectedSnapshot}». Мир поставлен на паузу — нажмите ▶ для продолжения.`,
      );
      void refreshLiveRuns().catch(() => undefined);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Не удалось загрузить сохранение.");
    }
  }

  const chooseAgent = useCallback((agentId: string) => {
    setSelectedAgentId(agentId);
  }, []);

  const isCompleted = snapshot?.run.status === "completed";

  return (
    <main className="observer-shell">
      <header className="topbar">
        <div className="brand-lockup">
          <span className="brand-lockup__signal" />
          <div><strong>АРЕНА ЦИВИЛИЗАЦИЙ</strong><small>Локальная лаборатория живого мира</small></div>
        </div>
        <div className="world-status">
          {snapshot ? <>
            <span><CloudRain size={16} weight="duotone" /> {snapshot.environment.weather}</span>
            <span>{snapshot.environment.temperature_c.toLocaleString("ru-RU")} °C{snapshot.environment.crisis ? " · КРИЗИС" : ""}</span>
            <strong>{isCompleted ? "ЭКСПЕРИМЕНТ ЗАВЕРШЁН" : `ДЕНЬ ${snapshot.environment.day}`}</strong>
            <span>{snapshot.environment.clock}</span>
          </> : <span><MapTrifold size={16} weight="duotone" /> Выберите или создайте мир</span>}
        </div>
        <div className="topbar__controls">
          <button type="button" className="icon-button" disabled={!snapshot || isCompleted} onClick={() => snapshot && void control({ paused: !snapshot.run.paused })} title={!snapshot ? "Сначала создайте или откройте мир" : isCompleted ? "Эксперимент завершён" : snapshot.run.paused ? "Продолжить" : "Пауза"}>
            {!snapshot || snapshot.run.paused ? <Play size={19} weight="fill" /> : <Pause size={19} weight="fill" />}
          </button>
          {[1, 3, 10].map((speed) => <button className={snapshot?.run.speed === speed ? "speed-button is-active" : "speed-button"} disabled={!snapshot || isCompleted} key={speed} type="button" onClick={() => void control({ speed })}>×{speed}</button>)}
          <button type="button" className="icon-button" disabled={!snapshot} onClick={() => void saveCurrent()} title="Сохранить"><FloppyDisk size={19} weight="duotone" /></button>
          <select className="snapshot-select" value={selectedSnapshot} onChange={(event) => setSelectedSnapshot(event.target.value)} aria-label="Выбрать сохранение">
            <option value="">Сохранения</option>
            {snapshots.map((name) => <option key={name} value={name}>{name}</option>)}
          </select>
          <button type="button" className="icon-button" onClick={() => void loadSelected()} title="Загрузить" disabled={!selectedSnapshot}><FolderOpen size={19} weight="duotone" /></button>
        </div>
      </header>

      <aside className="agent-rail">
        <section className="experiment-panel">
          <div className="section-heading"><span>ЭКСПЕРИМЕНТЫ</span><small>{liveRuns.length} активн.</small></div>
          <label>
            Сценарий
            <select value={modelKey} onChange={(event) => setModelKey(event.target.value)}>
              {catalog?.models.map((model) => <option key={`${model.provider}/${model.model}`} value={`${model.provider}/${model.model}`}>{model.label}</option>)}
            </select>
          </label>
          <p>{selectedModel?.description ?? "Загружаем доступные сценарии…"}</p>
          <label>
            Seed нового мира
            <input value={seed} onChange={(event) => setSeed(event.target.value)} inputMode="numeric" />
          </label>
          <button className="experiment-panel__start" type="button" onClick={() => void createOrContinueRun()} disabled={busy || !selectedModel}>
            {busy ? <CircleNotch className="spin" size={18} /> : <Play size={18} weight="fill" />} {busy ? "Подготовка…" : "Создать или открыть мир"}
          </button>
          <small>Новый seed создаёт отдельный мир; тот же seed открывает его прежнюю историю.</small>
          {liveRuns.length > 0 && <div className="experiment-panel__open">
            <label>
              Открытые миры
              <select value={selectedLiveRunId} onChange={(event) => setSelectedLiveRunId(event.target.value)}>
                {liveRuns.map((run) => <option key={run.run_id} value={run.run_id}>{liveRunLabel(run)}</option>)}
              </select>
            </label>
            <button type="button" className="experiment-panel__open-button" disabled={busy || !selectedLiveRunId} onClick={() => void openExistingRun(selectedLiveRunId)}>Открыть выбранный</button>
          </div>}
        </section>
        <div className="section-heading"><span>АГЕНТЫ</span><small>{snapshot?.agents.length ?? 0}</small></div>
        <div className="agent-list">
          {snapshot
            ? snapshot.agents.map((agent, index) => <AgentCard key={agent.id} agent={agent} index={index} selected={agent.id === selectedAgentId} onSelect={() => chooseAgent(agent.id)} />)
            : <p className="agent-list__empty">Здесь появятся личности выбранного мира.</p>}
        </div>
        <div className={`connection connection--${snapshot ? connection : "idle"}`}><span />{snapshot ? (connection === "live" ? "Поток подключён" : connection === "connecting" ? "Подключение…" : "Поток отключён") : "Мир ещё не открыт"}</div>
      </aside>

      <section className="map-panel">
        <div className="map-panel__heading">
          <span>КАРТА МИРА</span>
          <small>{snapshot ? `Seed ${snapshot.run.seed} · ${snapshot.map.width} × ${snapshot.map.height}` : "Выберите сценарий слева"}</small>
          <span className="map-panel__legend">{snapshot ? "Перетаскивайте карту для обзора" : "Рабочее пространство эксперимента"}</span>
        </div>
        {snapshot
          ? <WorldCanvas world={snapshot} selectedAgentId={selectedAgentId} onSelectAgent={chooseAgent} />
          : <div className="world-empty"><MapTrifold size={36} weight="duotone" /><strong>Мир ждёт запуска</strong><p>Выберите готовый сценарий или задайте seed для нового мира. Карта, агенты и хроника появятся здесь.</p></div>}
        <div className="map-panel__footer">
          <span><i className="legend-swatch legend-swatch--grass" />суша</span>
          <span><i className="legend-swatch legend-swatch--water" />вода</span>
          <span><i className="legend-swatch legend-swatch--forest" />лес</span>
          <span><i className="legend-swatch legend-swatch--rock" />камень</span>
          <small>{isCompleted ? "Эксперимент завершён: карта и хроника доступны для анализа и сохранения." : snapshot ? "Погода влияет на холод и здоровье; кризис фиксируется в хронике." : "Исследователь управляет запуском и временем, но не скрыто меняет мир."}</small>
        </div>
      </section>

      <aside className="chronicle-rail">
        <div className="chronicle-clock"><small>ВРЕМЯ МИРА</small><strong>{snapshot?.environment.clock ?? "—"}</strong><span>{snapshot ? `День ${snapshot.environment.day}` : "Мир не запущен"}</span></div>
        <div className="section-heading"><span>ХРОНИКА</span><small>{snapshot?.events.length ?? 0}</small></div>
        <ol className="event-list">
          {snapshot
            ? [...snapshot.events].reverse().map((event) => <li key={event.id}><time>{gameTime(event.minute).replace("День ", "Д")}</time><span>{event.text}</span></li>)
            : <li className="event-list__empty"><span>После запуска здесь появятся решения агентов, перемещения, сделки и события мира.</span></li>}
        </ol>
        <div className="instrument-panel">
          <div className="section-heading"><span>ПРИБОРЫ</span></div>
          <p><UsersThree size={16} weight="duotone" />Население <strong>{snapshot?.instruments.population ?? "—"}</strong></p>
          <p><Database size={16} weight="duotone" />Ресурсы <strong>{snapshot?.instruments.resources ?? "—"}</strong></p>
          <p><WarningCircle size={16} weight="duotone" />Обещания <strong>{snapshot?.instruments.active_promises ?? "—"}</strong></p>
        </div>
      </aside>

      <Inspector inspector={inspector} />
      <footer className="observer-footer">
        <span aria-live="polite">{notice}</span>
        <small>{snapshot ? (snapshot.run.modified ? "История содержит зафиксированное вмешательство." : "Мир работает независимо от открытого интерфейса.") : "Готовый сценарий — это выбор, а не обязательный режим."}</small>
      </footer>
    </main>
  );
}
