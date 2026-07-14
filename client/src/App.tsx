import { useCallback, useEffect, useMemo, useState } from "react";
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
import type { AgentInspector, AgentSummary, Catalog, WorldSnapshot } from "./types";

const DEFAULT_NAMES = ["Ада", "Борин", "Сайра"];

function meterValue(value: number, inverse = false) {
  return `${Math.max(0, Math.min(100, inverse ? 100 - value : value))}%`;
}

function gameTime(minute: number) {
  const day = Math.floor(minute / 1440) + 1;
  const hour = Math.floor((minute % 1440) / 60);
  const remainder = minute % 60;
  return `День ${day}, ${hour.toString().padStart(2, "0")}:${remainder.toString().padStart(2, "0")}`;
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
  const [notice, setNotice] = useState("Выберите модель и запустите первый эксперимент.");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.catalog()
      .then((nextCatalog) => {
        setCatalog(nextCatalog);
        if (nextCatalog.models[0]) setModelKey(`${nextCatalog.models[0].provider}/${nextCatalog.models[0].model}`);
      })
      .catch((error: Error) => setNotice(error.message));
    api.snapshots().then((response) => setSnapshots(response.snapshots)).catch(() => undefined);
  }, []);

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

  const selectedModel = useMemo(() => catalog?.models.find(
    (model) => `${model.provider}/${model.model}` === modelKey,
  ), [catalog, modelKey]);

  async function startRun() {
    if (!selectedModel) return;
    const numericSeed = Number(seed);
    if (!Number.isSafeInteger(numericSeed) || numericSeed < 0) {
      setNotice("Seed должен быть неотрицательным целым числом.");
      return;
    }
    setBusy(true);
    try {
      const created = await api.createRun({
        seed: numericSeed,
        width: 32,
        height: 32,
        agents: catalog?.agent_names ?? DEFAULT_NAMES,
        provider: selectedModel.provider,
        model: selectedModel.model,
      });
      const world = await api.observer(created.run_id);
      setSnapshot(world);
      setSelectedAgentId(world.agents[0]?.id ?? null);
      setNotice("Запуск создан. Мир остаётся на сервере и продолжит работу без открытого браузера.");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Не удалось создать запуск.");
    } finally {
      setBusy(false);
    }
  }

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
      const name = `observer-${snapshot.run.id.replace("run-", "")}`;
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
      setNotice(`Загружено сохранение «${selectedSnapshot}».`);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Не удалось загрузить сохранение.");
    }
  }

  const chooseAgent = useCallback((agentId: string) => {
    setSelectedAgentId(agentId);
  }, []);

  if (!snapshot) {
    return (
      <main className="launch-shell">
        <section className="launch-card">
          <div className="launch-card__eyebrow"><MapTrifold size={20} weight="duotone" /> НАБЛЮДАТЕЛЬ ЖИВОГО МИРА</div>
          <h1>Арена цивилизаций</h1>
          <p>Локальное окно в авторитетный мир. Браузер наблюдает, но не управляет его состоянием.</p>
          <label>
            Модель решений
            <select value={modelKey} onChange={(event) => setModelKey(event.target.value)}>
              {catalog?.models.map((model) => <option key={`${model.provider}/${model.model}`} value={`${model.provider}/${model.model}`}>{model.label}</option>)}
            </select>
          </label>
          <label>
            Seed мира
            <input value={seed} onChange={(event) => setSeed(event.target.value)} inputMode="numeric" />
          </label>
          <button className="launch-card__start" type="button" onClick={() => void startRun()} disabled={busy || !selectedModel}>
            {busy ? <CircleNotch className="spin" size={20} /> : <Play size={20} weight="fill" />} Запустить наблюдение
          </button>
          <small>{notice}</small>
        </section>
      </main>
    );
  }

  return (
    <main className="observer-shell">
      <header className="topbar">
        <div className="brand-lockup">
          <span className="brand-lockup__signal" />
          <div><strong>АРЕНА ЦИВИЛИЗАЦИЙ</strong><small>Локальный наблюдатель общества</small></div>
        </div>
        <div className="world-status">
          <span><CloudRain size={16} weight="duotone" /> {snapshot.environment.weather}</span>
          <strong>ДЕНЬ {snapshot.environment.day}</strong>
          <span>{snapshot.environment.clock}</span>
        </div>
        <div className="topbar__controls">
          <button type="button" className="icon-button" onClick={() => void control({ paused: !snapshot.run.paused })} title={snapshot.run.paused ? "Продолжить" : "Пауза"}>
            {snapshot.run.paused ? <Play size={19} weight="fill" /> : <Pause size={19} weight="fill" />}
          </button>
          {[1, 3, 10].map((speed) => <button className={snapshot.run.speed === speed ? "speed-button is-active" : "speed-button"} key={speed} type="button" onClick={() => void control({ speed })}>×{speed}</button>)}
          <button type="button" className="icon-button" onClick={() => void saveCurrent()} title="Сохранить"><FloppyDisk size={19} weight="duotone" /></button>
          <select className="snapshot-select" value={selectedSnapshot} onChange={(event) => setSelectedSnapshot(event.target.value)} aria-label="Выбрать сохранение">
            <option value="">Сохранения</option>
            {snapshots.map((name) => <option key={name} value={name}>{name}</option>)}
          </select>
          <button type="button" className="icon-button" onClick={() => void loadSelected()} title="Загрузить" disabled={!selectedSnapshot}><FolderOpen size={19} weight="duotone" /></button>
        </div>
      </header>

      <aside className="agent-rail">
        <div className="section-heading"><span>АГЕНТЫ</span><small>{snapshot.agents.length}</small></div>
        <div className="agent-list">
          {snapshot.agents.map((agent, index) => <AgentCard key={agent.id} agent={agent} index={index} selected={agent.id === selectedAgentId} onSelect={() => chooseAgent(agent.id)} />)}
        </div>
        <div className={`connection connection--${connection}`}><span />{connection === "live" ? "Поток подключён" : connection === "connecting" ? "Подключение…" : "Поток отключён"}</div>
      </aside>

      <section className="map-panel">
        <div className="map-panel__heading">
          <span>КАРТА МИРА</span>
          <small>Seed {snapshot.run.seed} · {snapshot.map.width} × {snapshot.map.height}</small>
          <span className="map-panel__legend">Перетаскивайте карту для обзора</span>
        </div>
        <WorldCanvas world={snapshot} selectedAgentId={selectedAgentId} onSelectAgent={chooseAgent} />
        <div className="map-panel__footer">
          <span><i className="legend-swatch legend-swatch--grass" />суша</span>
          <span><i className="legend-swatch legend-swatch--water" />вода</span>
          <span><i className="legend-swatch legend-swatch--forest" />лес</span>
          <span><i className="legend-swatch legend-swatch--rock" />камень</span>
          <small>Визуальная погода не меняет правила мира в этом блоке.</small>
        </div>
      </section>

      <aside className="chronicle-rail">
        <div className="chronicle-clock"><small>ВРЕМЯ МИРА</small><strong>{snapshot.environment.clock}</strong><span>День {snapshot.environment.day}</span></div>
        <div className="section-heading"><span>ХРОНИКА</span><small>{snapshot.events.length}</small></div>
        <ol className="event-list">
          {[...snapshot.events].reverse().map((event) => <li key={event.id}><time>{gameTime(event.minute).replace("День ", "Д")}</time><span>{event.text}</span></li>)}
        </ol>
        <div className="instrument-panel">
          <div className="section-heading"><span>ПРИБОРЫ</span></div>
          <p><UsersThree size={16} weight="duotone" />Население <strong>{snapshot.instruments.population}</strong></p>
          <p><Database size={16} weight="duotone" />Ресурсы <strong>{snapshot.instruments.resources}</strong></p>
          <p><WarningCircle size={16} weight="duotone" />Обещания <strong>{snapshot.instruments.active_promises}</strong></p>
        </div>
      </aside>

      <Inspector inspector={inspector} />
      <footer className="observer-footer">
        <span>{notice}</span>
        <small>{snapshot.run.modified ? "Загруженный запуск: история помечена как импортированная." : "Авторитетный мир работает независимо от интерфейса."}</small>
      </footer>
    </main>
  );
}
