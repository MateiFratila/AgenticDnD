# Agentic DnD Backend

Turn-based D&D simulation backend with a deterministic world engine, LLM adjudication, mutation extraction, orchestration, and snapshot inspection tools.

Architecture notes: [docs/architecture.md](docs/architecture.md)

## Project Layout

- `assets/`: Adventure data, PCs, and homebrew rules JSON files.
- `backend/world/`: Immutable world state, snapshot-first loader, mutation schema, dispatcher.
- `backend/agents/`: Agent base classes and typed response contracts, including the PC/NPC intent generator.
- `backend/llm/`: LLM client and prompt loading utilities.
- `backend/orchestrator/`: Turn loop orchestrator and snapshot tooling.
- `backend/prompts/`: System prompts for intent generation, adjudication, and extraction.
- `test_*.py`: Script-style test files covering major subsystems.

## Environment Setup

1. Create virtual environment:
	 `python3.11 -m venv .venv`
2. Activate environment:
	 `source .venv/bin/activate`
3. Install dependencies:
	 `pip install -r backend/requirements.txt`

## Command Reference

### Core Test Commands

- Run world loader and dispatcher checks:
	`python test_loader.py`
- Run agent prompt and initialization checks:
	`python test_agents.py`
- Run typed contract validation checks:
	`python test_agent_contracts.py`
- Run orchestrator flow checks:
	`python test_orchestrator.py`
- Run snapshot utility checks:
	`python test_snapshot_tools.py`
- Run REST API tests:
	`python test_api.py`

### REST API Commands

- Start development server:
	`uvicorn backend.main:app --reload`
  The server will initialize the game engine on startup and listen on `http://localhost:8000`.
- View interactive API documentation:
	`http://localhost:8000/docs` (Swagger UI)

### Snapshot Tooling Commands

- List all persisted snapshots:
	`python -m backend.orchestrator.snapshot_tools list`
- List snapshots from a custom directory:
	`python -m backend.orchestrator.snapshot_tools list --dir <path>`
- Diff two explicit snapshots:
	`python -m backend.orchestrator.snapshot_tools diff <older.json> <newer.json>`
- Diff the latest two snapshots automatically:
	`python -m backend.orchestrator.snapshot_tools diff-latest`
- Diff the latest two snapshots from a custom directory:
	`python -m backend.orchestrator.snapshot_tools diff-latest --dir <path>`
- List current-session snapshots over HTTP:
	`GET /api/snapshots`
- Diff the latest two current-session snapshots over HTTP:
	`GET /api/snapshots/diff-latest`

## Tooling Overview

### Table Orchestrator

File: `backend/orchestrator/table_orchestrator.py`

What it does:
- Runs the main turn loop as `intent generation (when needed) -> adjudication -> extraction -> mutation application`.
- Normalizes both player-submitted text and generated intents into one internal `ResolvedAction` contract before adjudication.
- Supports deterministic inventory updates through `item_add` and `item_remove` mutations on PC/NPC inventories, so approved loot or item consumption can now persist in snapshots.
- Treats searched or looted corpses as a simple dead-actor condition (for example `looted`), keeping the state deterministic without introducing a separate corpse object model.
- Automatically drops back to normal party turn flow when an encounter is marked inactive or cleared, preventing stale encounter pointers from hijacking subsequent turns.
- Uses encounter-owned combat state (`turn_order`, `current_turn_index`, `round_count`) whenever an encounter is active, instead of relying only on a top-level PC turn pointer.
- Builds a scoped payload focused on the acting PC or NPC, current scene, active objectives, recent turn history, and nearby room connections instead of dumping the full world state.
- Automatically generates an action when `/api/advance` receives an empty `action` string for the active PC.
- Auto-resolves encounter NPC turns through the Intent Agent after a committed PC turn until control returns to the next PC slot, and records compact `npc_turns` summaries for the API response.
- Uses loop failsafes during NPC auto-resolution (hard turn cap, repeated-state detection, and no-progress detection) to prevent runaway recursion.
- Keeps the same actor awaited when a ruling asks for an unresolved roll/check, rather than advancing turn prematurely.
- Records adjudicator rulings into `world.turn_log` so future turns retain DM-facing narrative history, while extractor/world entries can still capture canonical state changes.
- Stores session metadata in world state (`active_actor_id`, `awaiting_input_from`, `world_version`).
- Persists a world snapshot JSON as the final step of each loop.

Snapshot behavior:
- Default output directory: `artifacts/world_snapshots/`
- Snapshot naming:
  `s_<game_session_id>_l_XXXX_a_<actor_id>.json`
- Disable snapshots by passing `snapshot_dir=None` when creating the orchestrator.

### Snapshot Tools

File: `backend/orchestrator/snapshot_tools.py`

What it does:
- Lists snapshot files (`s_*_l_*.json`).
- Loads snapshot JSON.
- Produces readable flattened diffs between snapshots.
- Supports automatic latest-to-latest diff with `diff-latest`.
- Shares snapshot persistence/listing helpers with the orchestrator and REST API.

### Adventure Loader

File: `backend/world/loader.py`

What it does:
- Attempts snapshot restore first on every load.
- Restores the latest snapshot globally, or latest for a specific `game_session_id` when provided.
- Falls back to creating a fresh world from `assets/` if no matching snapshot exists.
- Generates a short 5-character `game_session_id` on fresh world creation.

### REST API

File: `backend/main.py` (app factory) and `backend/api/` (routes and models)

What it does:
- Wraps `TableOrchestrator` in a FastAPI application.
- Initializes the game engine on startup (loads world from snapshots or assets, creates agents, starts orchestrator).
- Exposes POST `/api/advance` to process player actions, GET `/api/rewind` to drop the newest snapshot and restore the previous one, and snapshot inspection endpoints at `GET /api/snapshots` and `GET /api/snapshots/diff-latest`.
- Accepts a nested payload shaped like `{ "actor": { "actor_id": "...", "action": "..." } }`; `actor.action` may be an empty string or `null`, in which case the intent agent generates the acting PC's next move before adjudication.
- Returns the full normalized `ResolvedAction` under `data.actor`, so the API echoes back the effective `actor_id`, `action`, `source`, and any optional intent metadata that was actually processed.
- Includes `npc_turns` in the `/api/advance` response for any NPC actions auto-resolved before control returns to the next PC.
- Routes actions through Intent/Adjudicator/Extractor layers and applies mutations to world state.
- Persists snapshots after each turn.
- Supports questions (answered without turn advance) and action intents (approved/rejected, may advance turn).

## Test Inventory

### `test_loader.py`

Covers:
- Fresh world initialization from assets when no snapshot exists.
- Snapshot-first restore behavior (including `game_session_id` filtering).
- Encounter turn-state scaffolding (`turn_order`, `current_turn_index`) on fresh loads and restores.
- Immutable update behavior on dataclass state.
- Deterministic dispatcher mutation application, including room membership syncing and inventory item add/remove behavior.
- Cleanup-safe temporary snapshot directories in tests.

### `test_agents.py`

Covers:
- Prompt loading for intent, adjudicator, and extractor.
- BaseAgent initialization and configuration for all three agent roles.
- LLM client initialization path.

### `test_agent_contracts.py`

Covers:
- Adjudicator response schema parsing and validation.
- Intent response schema parsing and validation.
- Extractor mutation array schema parsing and validation, including inventory mutations.
- Rejection/error cases (missing alternatives, invalid mutation values).

### `test_orchestrator.py`

Covers:
- Approved turn flow with extractor route and mutation application.
- Empty-action flow that uses the intent agent to generate a move.
- Encounter-owned turn order progression, round wrapping, and NPC routing through the intent agent.
- Safe NPC auto-resolution with failsafe caps and summaries.
- Rejected flow with no commit.
- Agent-wrapper (`from_agents`) payload handling.
- World session metadata updates and turn progression.

### `test_snapshot_tools.py`

Covers:
- Snapshot listing order.
- Direct file diff behavior.
- `diff-latest` success path and insufficient-snapshot failure path.

### `test_api.py`

Covers:
- App lifespan initialization (agent creation, orchestrator setup).
- Endpoint contract validation and response models.
- Actor turn validation (reject actions from non-active actor).
- Nested `/api/advance` actor payload handling, including generated intent flow, normalized `ResolvedAction` serialization under `data.actor`, `npc_turns` serialization, and corpse-looting state represented canonically via dead-target conditions.
- Approved and rejected action flows via HTTP POST.
- Rewind behavior that deletes the newest session snapshot and reloads the previous one.
- Snapshot listing and latest-diff inspection over HTTP.
- World state persistence across requests.
- Error handling and graceful fallback responses.

## README Maintenance Rule

When any tool is added or changed, update this README in the same change set.

Minimum required updates:
1. Add or revise command(s) in Command Reference.
2. Add or revise behavior in Tooling Overview.
3. Add or revise test coverage notes in Test Inventory.

Pull request checklist item:
- [ ] If tooling changed, README command/tool/test sections were updated.

