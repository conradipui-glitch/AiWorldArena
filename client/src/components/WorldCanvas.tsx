import { useEffect, useRef } from "react";
import Phaser from "phaser";
import type { WorldSnapshot } from "../types";

type WorldCanvasProps = {
  world: WorldSnapshot | null;
  selectedAgentId: string | null;
  onSelectAgent: (agentId: string) => void;
};

class ObserverScene extends Phaser.Scene {
  private world: WorldSnapshot | null = null;
  private selectedAgentId: string | null = null;
  private staticLayer!: Phaser.GameObjects.Container;
  private dynamicLayer!: Phaser.GameObjects.Container;
  private darkness!: Phaser.GameObjects.Rectangle;
  private staticSignature = "";
  private hasFittedCamera = false;
  private onAgentSelected: (agentId: string) => void = () => undefined;
  private agentPositions = new Map<string, { x: number; y: number }>();

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
    this.input.on("pointermove", (pointer: Phaser.Input.Pointer) => {
      if (!pointer.isDown) return;
      this.cameras.main.scrollX -= pointer.velocity.x / this.cameras.main.zoom;
      this.cameras.main.scrollY -= pointer.velocity.y / this.cameras.main.zoom;
    });
    this.renderWorld();
  }

  setObserverState(
    world: WorldSnapshot,
    selectedAgentId: string | null,
    onAgentSelected: (agentId: string) => void,
  ) {
    this.world = world;
    this.selectedAgentId = selectedAgentId;
    this.onAgentSelected = onAgentSelected;
    if (this.sys && this.sys.isActive()) this.renderWorld();
  }

  refitCamera() {
    this.hasFittedCamera = false;
    this.renderWorld();
  }

  private renderWorld() {
    if (!this.world || !this.staticLayer || !this.dynamicLayer) return;
    const { map } = this.world;
    const tileSize = 34;
    const worldWidth = map.width * tileSize;
    const worldHeight = map.height * tileSize;
    const signature = `${map.width}x${map.height}:${map.tiles.map((tile) => tile.terrain).join(",")}`;

    if (signature !== this.staticSignature) {
      this.staticSignature = signature;
      this.staticLayer.removeAll(true);
      map.tiles.forEach((tile) => {
        const image = this.add
          .image(tile.x * tileSize + tileSize / 2, tile.y * tileSize + tileSize / 2, `terrain-${tile.terrain}`)
          .setDisplaySize(tileSize + 1, tileSize + 1)
          .setOrigin(0.5);
        this.staticLayer.add(image);
      });
      this.cameras.main.setBounds(0, 0, worldWidth, worldHeight);
      this.hasFittedCamera = false;
    }

    this.dynamicLayer.removeAll(true);
    map.resources.forEach((resource) => {
      const marker = this.add
        .image(resource.x * tileSize + tileSize / 2, resource.y * tileSize + tileSize / 2, `resource-${resource.kind}`)
        .setDisplaySize(tileSize * 0.76, tileSize * 0.76);
      this.dynamicLayer.add(marker);
    });
    map.structures.forEach((structure) => {
      const marker = this.add
        .image(structure.x * tileSize + tileSize / 2, structure.y * tileSize + tileSize / 2, `structure-${structure.kind}`)
        .setDisplaySize(tileSize * 0.9, tileSize * 0.9);
      this.dynamicLayer.add(marker);
    });
    this.world.agents.forEach((agent, index) => {
      const destination = {
        x: agent.position.x * tileSize + tileSize / 2,
        y: agent.position.y * tileSize + tileSize / 2,
      };
      const prior = this.agentPositions.get(agent.id);
      const avatar = this.add
        .image(prior?.x ?? destination.x, prior?.y ?? destination.y, `agent-${(index % 3) + 1}`)
        .setDisplaySize(tileSize * 0.94, tileSize * 0.94)
        .setInteractive({ useHandCursor: true });
      if (agent.id === this.selectedAgentId) avatar.setTint(0xf1c66c);
      if (prior && (prior.x !== destination.x || prior.y !== destination.y)) {
        this.tweens.add({
          targets: avatar,
          x: destination.x,
          y: destination.y,
          duration: 280,
          ease: "Sine.out",
        });
      }
      avatar.on("pointerup", () => this.onAgentSelected(agent.id));
      this.dynamicLayer.add(avatar);
      this.agentPositions.set(agent.id, destination);
    });
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

export function WorldCanvas({ world, selectedAgentId, onSelectAgent }: WorldCanvasProps) {
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
    if (world) sceneRef.current?.setObserverState(world, selectedAgentId, onSelectAgent);
  }, [world, selectedAgentId, onSelectAgent]);

  return <div className="world-canvas" ref={hostRef} aria-label="Интерактивная карта мира" />;
}
