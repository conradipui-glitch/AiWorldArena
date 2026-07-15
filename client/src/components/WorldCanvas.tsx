import { useEffect, useRef } from "react";
import { ArrowsOut, MagnifyingGlassMinus, MagnifyingGlassPlus } from "@phosphor-icons/react";
import Phaser from "phaser";
import type { AgentSummary, WorldSnapshot } from "../types";

type MapPosition = { x: number; y: number };

type WorldCanvasProps = {
  world: WorldSnapshot | null;
  selectedAgentId: string | null;
  onSelectAgent: (agentId: string) => void;
  placementMode?: boolean;
  placement?: MapPosition | null;
  onMapPosition?: (position: MapPosition) => void;
};

const TILE_SIZE = 34;

class ObserverScene extends Phaser.Scene {
  private world: WorldSnapshot | null = null;
  private selectedAgentId: string | null = null;
  private staticLayer!: Phaser.GameObjects.Container;
  private dynamicLayer!: Phaser.GameObjects.Container;
  private overlayLayer!: Phaser.GameObjects.Container;
  private darkness!: Phaser.GameObjects.Rectangle;
  private staticSignature = "";
  private hasFittedCamera = false;
  private placementMode = false;
  private placement: MapPosition | null = null;
  private onAgentSelected: (agentId: string) => void = () => undefined;
  private onPositionSelected: (position: MapPosition) => void = () => undefined;
  private agentPositions = new Map<string, MapPosition>();

  constructor() {
    super("observer-world");
  }

  preload() {
    ["water", "sand", "grass", "forest", "rock"].forEach((name) => {
      this.load.image(`terrain-${name}`, `/assets/${name}.png`);
    });
    ["wood", "stone", "berry", "water"].forEach((name) => {
      this.load.image(`resource-${name}`, `/assets/resource-${name}.png`);
    });
    ["fire", "shelter"].forEach((name) => {
      this.load.image(`structure-${name}`, `/assets/structure-${name}.png`);
    });
    this.load.image("structure-storage", "/assets/structure-storage.svg");
    [1, 2, 3].forEach((number) => {
      this.load.image(`agent-${number}`, `/assets/agent-${number}.png`);
    });
  }

  create() {
    this.cameras.main.setBackgroundColor("#0d1822");
    this.staticLayer = this.add.container(0, 0);
    this.dynamicLayer = this.add.container(0, 0);
    this.darkness = this.add.rectangle(0, 0, 1, 1, 0x08111c, 0).setOrigin(0);
    this.overlayLayer = this.add.container(0, 0);
    this.input.on("pointermove", (pointer: Phaser.Input.Pointer) => {
      if (!pointer.isDown || this.placementMode) return;
      this.cameras.main.scrollX -= pointer.velocity.x / this.cameras.main.zoom;
      this.cameras.main.scrollY -= pointer.velocity.y / this.cameras.main.zoom;
    });
    this.input.on("pointerup", (pointer: Phaser.Input.Pointer) => {
      if (!this.placementMode || !this.world) return;
      const dragged = Phaser.Math.Distance.Between(pointer.downX, pointer.downY, pointer.x, pointer.y);
      if (dragged > 8) return;
      const point = this.cameras.main.getWorldPoint(pointer.x, pointer.y);
      const position = {
        x: Phaser.Math.Clamp(Math.floor(point.x / TILE_SIZE), 0, this.world.map.width - 1),
        y: Phaser.Math.Clamp(Math.floor(point.y / TILE_SIZE), 0, this.world.map.height - 1),
      };
      this.onPositionSelected(position);
    });
    this.input.on("wheel", (pointer: Phaser.Input.Pointer, _objects: unknown[], _dx: number, dy: number) => {
      this.changeZoom(dy > 0 ? 0.86 : 1.16, pointer);
    });
    this.renderWorld();
  }

  setObserverState(
    world: WorldSnapshot,
    selectedAgentId: string | null,
    onAgentSelected: (agentId: string) => void,
    placementMode: boolean,
    placement: MapPosition | null,
    onPositionSelected: (position: MapPosition) => void,
  ) {
    this.world = world;
    this.selectedAgentId = selectedAgentId;
    this.onAgentSelected = onAgentSelected;
    this.placementMode = placementMode;
    this.placement = placement;
    this.onPositionSelected = onPositionSelected;
    if (this.sys && this.sys.isActive()) this.renderWorld();
  }

  refitCamera() {
    this.hasFittedCamera = false;
    this.renderWorld();
  }

  zoomIn() { this.changeZoom(1.2); }
  zoomOut() { this.changeZoom(0.84); }
  resetCamera() { this.hasFittedCamera = false; this.renderWorld(); }

  private changeZoom(factor: number, pointer?: Phaser.Input.Pointer) {
    const camera = this.cameras.main;
    const focusX = pointer?.x ?? this.scale.width / 2;
    const focusY = pointer?.y ?? this.scale.height / 2;
    const before = camera.getWorldPoint(focusX, focusY);
    camera.setZoom(Phaser.Math.Clamp(camera.zoom * factor, 0.35, 3.25));
    const after = camera.getWorldPoint(focusX, focusY);
    camera.scrollX += before.x - after.x;
    camera.scrollY += before.y - after.y;
  }

  private renderWorld() {
    if (!this.world || !this.staticLayer || !this.dynamicLayer || !this.overlayLayer) return;
    const { map } = this.world;
    const worldWidth = map.width * TILE_SIZE;
    const worldHeight = map.height * TILE_SIZE;
    const signature = `${map.width}x${map.height}:${map.tiles.map((tile) => tile.terrain).join(",")}`;

    if (signature !== this.staticSignature) {
      this.staticSignature = signature;
      this.staticLayer.removeAll(true);
      map.tiles.forEach((tile) => {
        const image = this.add
          .image(tile.x * TILE_SIZE + TILE_SIZE / 2, tile.y * TILE_SIZE + TILE_SIZE / 2, `terrain-${tile.terrain}`)
          .setDisplaySize(TILE_SIZE + 1, TILE_SIZE + 1)
          .setOrigin(0.5);
        this.staticLayer.add(image);
      });
      this.cameras.main.setBounds(0, 0, worldWidth, worldHeight);
      this.hasFittedCamera = false;
    }

    this.dynamicLayer.removeAll(true);
    this.overlayLayer.removeAll(true);
    map.resources.forEach((resource) => {
      const marker = this.add
        .image(resource.x * TILE_SIZE + TILE_SIZE / 2, resource.y * TILE_SIZE + TILE_SIZE / 2, `resource-${resource.kind}`)
        .setDisplaySize(TILE_SIZE * 0.76, TILE_SIZE * 0.76);
      this.dynamicLayer.add(marker);
    });
    map.structures.forEach((structure) => {
      const marker = this.add
        .image(structure.x * TILE_SIZE + TILE_SIZE / 2, structure.y * TILE_SIZE + TILE_SIZE / 2, `structure-${structure.kind}`)
        .setDisplaySize(TILE_SIZE * 0.9, TILE_SIZE * 0.9);
      this.dynamicLayer.add(marker);
    });
    this.world.agents.forEach((agent, index) => {
      const destination = {
        x: agent.position.x * TILE_SIZE + TILE_SIZE / 2,
        y: agent.position.y * TILE_SIZE + TILE_SIZE / 2,
      };
      const prior = this.agentPositions.get(agent.id);
      const avatar = this.add
        .image(prior?.x ?? destination.x, prior?.y ?? destination.y, `agent-${(index % 3) + 1}`)
        .setDisplaySize(TILE_SIZE * 0.94, TILE_SIZE * 0.94)
        .setInteractive({ useHandCursor: true });
      const creatureTint: number | undefined = ({ wolf: 0xaec0cc, bear: 0xb78b68, boar: 0xc98a79 } as Partial<Record<AgentSummary["species"], number>>)[agent.species];
      if (creatureTint) avatar.setTint(creatureTint);
      if (agent.id === this.selectedAgentId) avatar.setTint(0xf1c66c);
      if (prior && (prior.x !== destination.x || prior.y !== destination.y)) {
        this.tweens.add({ targets: avatar, x: destination.x, y: destination.y, duration: 280, ease: "Sine.out" });
      }
      avatar.on("pointerup", () => {
        if (!this.placementMode) this.onAgentSelected(agent.id);
      });
      this.dynamicLayer.add(avatar);
      this.agentPositions.set(agent.id, destination);
    });

    (this.world.dialogues ?? []).forEach((dialogue) => {
      const agent = this.world?.agents.find((item) => item.id === dialogue.agent_id);
      if (!agent) return;
      const x = agent.position.x * TILE_SIZE + TILE_SIZE / 2;
      const y = agent.position.y * TILE_SIZE - 13;
      const text = this.add.text(x, y, dialogue.text, {
        color: "#13212b",
        fontFamily: "IBM Plex Sans, sans-serif",
        fontSize: "11px",
        wordWrap: { width: 150 },
        align: "center",
      }).setOrigin(0.5, 1);
      const bounds = text.getBounds();
      const background = this.add.rectangle(x, y - bounds.height / 2, bounds.width + 16, bounds.height + 10, 0xe8eff0, 0.96)
        .setStrokeStyle(1, 0x314d5f)
        .setOrigin(0.5);
      this.overlayLayer.add([background, text]);
    });

    if (this.placement) {
      const marker = this.add.rectangle(
        this.placement.x * TILE_SIZE + TILE_SIZE / 2,
        this.placement.y * TILE_SIZE + TILE_SIZE / 2,
        TILE_SIZE - 4,
        TILE_SIZE - 4,
        0xe3b967,
        0.18,
      ).setStrokeStyle(2, 0xf1c66c);
      this.overlayLayer.add(marker);
    }

    this.darkness
      .setPosition(0, 0)
      .setSize(worldWidth, worldHeight)
      .setFillStyle(0x07111d, this.world.environment.night_overlay);

    if (!this.hasFittedCamera) {
      const horizontal = this.scale.width / worldWidth;
      const vertical = this.scale.height / worldHeight;
      this.cameras.main.setZoom(Phaser.Math.Clamp(Math.min(horizontal, vertical) * 0.94, 0.35, 1.25));
      this.cameras.main.centerOn(worldWidth / 2, worldHeight / 2);
      this.hasFittedCamera = true;
    }
  }
}

export function WorldCanvas({
  world,
  selectedAgentId,
  onSelectAgent,
  placementMode = false,
  placement = null,
  onMapPosition = () => undefined,
}: WorldCanvasProps) {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const gameRef = useRef<Phaser.Game | null>(null);
  const sceneRef = useRef<ObserverScene | null>(null);

  useEffect(() => {
    if (!hostRef.current || gameRef.current) return;
    const scene = new ObserverScene();
    const game = new Phaser.Game({
      type: Phaser.AUTO,
      parent: hostRef.current,
      backgroundColor: "#0d1822",
      scene,
      scale: { mode: Phaser.Scale.RESIZE, width: 1, height: 1 },
      render: { antialias: false, pixelArt: true },
    });
    sceneRef.current = scene;
    gameRef.current = game;
    const observer = new ResizeObserver(() => scene.refitCamera());
    observer.observe(hostRef.current);
    return () => {
      observer.disconnect();
      game.destroy(true);
      gameRef.current = null;
      sceneRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (world) {
      sceneRef.current?.setObserverState(
        world,
        selectedAgentId,
        onSelectAgent,
        placementMode,
        placement,
        onMapPosition,
      );
    }
  }, [world, selectedAgentId, onSelectAgent, placementMode, placement, onMapPosition]);

  return (
    <div className={`world-canvas-shell ${placementMode ? "is-placing" : ""}`}>
      <div className="world-canvas" ref={hostRef} aria-label="Интерактивная карта мира" />
      <div className="map-zoom" aria-label="Масштаб карты">
        <button type="button" onClick={() => sceneRef.current?.zoomIn()} title="Увеличить карту"><MagnifyingGlassPlus size={18} /></button>
        <button type="button" onClick={() => sceneRef.current?.zoomOut()} title="Уменьшить карту"><MagnifyingGlassMinus size={18} /></button>
        <button type="button" onClick={() => sceneRef.current?.resetCamera()} title="Показать всю карту"><ArrowsOut size={18} /></button>
      </div>
      {placementMode && <div className="placement-hint">Щёлкните по свободной клетке карты</div>}
    </div>
  );
}
