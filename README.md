# Agentic DnD Backend

Turn-based D&D simulation backend with a deterministic world engine, LLM adjudication, mutation extraction, orchestration, and snapshot inspection tools.

## Project Layout

- `assets/`: Adventure data, PCs, and homebrew rules JSON files.
- `backend/world/`: Immutable world state, snapshot-first loader, mutation schema, dispatcher.
- `backend/agents/`: Agent base classes and typed response contracts.
- `backend/llm/`: LLM client and prompt loading utilities.
- `backend/orchestrator/`: Turn loop orchestrator and snapshot tooling.
- `backend/prompts/`: System prompts for adjudicator and extractor.
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

## Tooling Overview

### Table Orchestrator

File: `backend/orchestrator/table_orchestrator.py`

What it does:
- Runs one turn loop: adjudication -> extraction -> mutation application.
- Stores session metadata in world state (`active_actor_id`, `awaiting_input_from`, `world_version`).
- Persists a world snapshot JSON as the final step of each loop.

Snapshot behavior:
- Default output directory: `artifacts/world_snapshots/`
- Snapshot naming:
  `session_<game_session_id>_loop_XXXX_turn_XXXX_v_XXXX_actor_<actor_id>.json`
- Disable snapshots by passing `snapshot_dir=None` when creating the orchestrator.

### Snapshot Tools

File: `backend/orchestrator/snapshot_tools.py`

What it does:
- Lists snapshot files (`*loop_*.json`, including session-prefixed names).
- Loads snapshot JSON.
- Produces readable flattened diffs between snapshots.
- Supports automatic latest-to-latest diff with `diff-latest`.

### Adventure Loader

File: `backend/world/loader.py`

What it does:
- Attempts snapshot restore first on every load.
- Restores the latest snapshot globally, or latest for a specific `game_session_id` when provided.
- Falls back to creating a fresh world from `assets/` if no matching snapshot exists.
- Generates a short 5-character `game_session_id` on fresh world creation.

## Test Inventory

### `test_loader.py`

Covers:
- Fresh world initialization from assets when no snapshot exists.
- Snapshot-first restore behavior (including `game_session_id` filtering).
- Immutable update behavior on dataclass state.
- Deterministic dispatcher mutation application and room membership syncing.
- Cleanup-safe temporary snapshot directories in tests.

### `test_agents.py`

Covers:
- Prompt loading for adjudicator and extractor.
- BaseAgent initialization and configuration.
- LLM client initialization path.

### `test_agent_contracts.py`

Covers:
- Adjudicator response schema parsing and validation.
- Extractor mutation array schema parsing and validation.
- Rejection/error cases (missing alternatives, invalid mutation values).

### `test_orchestrator.py`

Covers:
- Approved turn flow with extractor route and mutation application.
- Rejected flow with no commit.
- Agent-wrapper (`from_agents`) payload handling.
- World session metadata updates and turn progression.

### `test_snapshot_tools.py`

Covers:
- Snapshot listing order.
- Direct file diff behavior.
- `diff-latest` success path and insufficient-snapshot failure path.

## README Maintenance Rule

When any tool is added or changed, update this README in the same change set.

Minimum required updates:
1. Add or revise command(s) in Command Reference.
2. Add or revise behavior in Tooling Overview.
3. Add or revise test coverage notes in Test Inventory.

Pull request checklist item:
- [ ] If tooling changed, README command/tool/test sections were updated.

