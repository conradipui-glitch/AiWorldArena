# Block 3 visual QA

## Comparison target

- Source visual truth: `C:\Users\kato55\.codex\generated_images\019f6152-5662-76b2-9c36-8aa3fed401ec\exec-3aadb350-d442-4b9a-89c2-743c9707ac2c.png` — selected option 2.
- Implementation capture: `C:\REPO\AiWorldArena\work\block3-observer-map.png`.
- Focused inspector capture: `C:\REPO\AiWorldArena\work\block3-observer-inspector.png`.
- Side-by-side evidence: `C:\REPO\AiWorldArena\work\block3-design-comparison.png`.
- Browser viewport: 1280 × 720. The selected reference was created for 1440 × 1024;
  comparison was normalized to the available desktop crop. The narrower viewport
  naturally scrolls to the lower inspector rather than fitting it all at once.
- State: a three-agent, paused deterministic run after initial observations and
  one movement; agent Ада is selected.

## Findings

### Pass 1

- [P1] Inspector heading overlapped the selected agent name at the top of the
  lower panel.
  - Location: `.inspector > .section-heading`.
  - Evidence: focused browser capture showed `ИНСПЕКТОРАда` as one overlapping
    visual token.
  - Impact: made the selected-agent context difficult to scan.
  - Fix: constrained the heading to the inspector width, made the parent a
    positioned grid, and assigned explicit grid rows to the identity, decision
    and detail regions.

### Pass 2

No actionable P0, P1 or P2 differences remain for the Block 3 MVP target.

Intentional, non-blocking differences from the concept image:

- The MVP has three agents rather than a twelve-agent roster, matching the
  approved first experiment scope.
- UI content is Russian by explicit project decision; the visual reference had
  English placeholder text.
- The current world is generated from the authoritative 32 × 32 server map,
  rather than a pre-composed illustration. This is required for live replay and
  observation.
- The source's large circular time dial was replaced with a compact clock so
  pause, speed and save/load remain visible in the smaller desktop viewport.

## Fidelity surfaces

- **Fonts and typography:** IBM Plex Sans and IBM Plex Mono are bundled with
  Cyrillic subsets. The compact technical hierarchy, controlled letter spacing,
  strong world-time numerals and clear Russian labels are legible at the tested
  size. No clipped primary labels were observed.
- **Spacing and layout rhythm:** The chosen three-rail anatomy is preserved:
  agent roster, central map, event chronicle, and a lower inspector. Borders are
  crisp and square as in the reference. The 720px viewport scrolls vertically
  to the inspector; persistent runtime controls remain at the top.
- **Colors and tokens:** The implementation uses a restrained blue-black field
  palette with pale cyan data text, green live indicators and one amber selected
  state. It avoids generic gradients and keeps the map as the visual focus.
- **Image quality and asset fidelity:** Phaser uses original raster terrain,
  resource, structure and agent assets generated for this observer direction;
  icons come from Phosphor rather than custom SVG or CSS drawings. Assets remain
  sharp with pixel rendering enabled.
- **Copy and content:** All visible labels, status messages, errors, event text
  and inspector content are Russian. The copy explains what the user can
  observe, without claiming browser authority over the world.

## Primary interactions tested

1. Opened the local start screen and chose the available local decision mode.
2. Created a new run and received a live server snapshot.
3. Verified direct WebSocket connection, event updates and `Поток подключён`.
4. Resumed then paused the run; world time and chronicle advanced.
5. Selected agent Ада and verified observation, known map, memory, beliefs,
   relations and promise sections.
6. Checked browser console after the final pass: no errors.

## Follow-up polish

- [P3] When the experiment grows beyond three agents, add compact roster
  filtering rather than widening the left rail.
- [P3] A later simulation-weather block can make weather physical while keeping
  the existing observer presentation contract.

final result: passed

## Block 4 regression pass — 2026-07-15

- Запуск по умолчанию показывает русский сценарий «три агента, семь дней» на карте 48×48.
- Верхняя панель отображает авторитетные погоду и температуру; пояснение под картой больше не
  называет погоду декоративной.
- Хроника показывает создание совместного проекта, а карточки — русские названия текущих действий.
- Новое пиксельное хранилище загружается как отдельный Phaser asset без missing-texture marker.
- Pause/resume, ×10 и read-only WebSocket продолжают работать; console warnings/errors отсутствуют.
- Выбранная композиция option 2, палитра и русскоязычная иерархия не изменены.

Block 4 regression result: passed
