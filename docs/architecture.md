# Architecture

## Overview

This project is a Python backend for an agentic D&D simulation. The main subsystems are:

- `backend/world`: immutable world state, asset/snapshot loader, mutation schema, dispatcher
- `backend/agents`: agent interfaces and typed response contracts
- `backend/llm`: LLM client and prompt loading
- `backend/orchestrator`: turn loop orchestration and snapshot tooling

## Core Runtime Design

The runtime is intentionally split into three layers:

1. `Adjudicator`
   Decides whether an action is legal, produces a ruling, and specifies where the result should route next.
2. `Extractor`
   Converts an approved adjudication into typed world mutations.
3. `Dispatcher`
   Applies mutations deterministically to `WorldState`.

Only the orchestrator coordinates these layers.

## Source Of Truth

`WorldState` is the source of truth for both game state and session state.

In addition to rooms, PCs, NPCs, encounters, and objectives, `WorldState` carries orchestration/session metadata:

- `game_session_id`
- `active_actor_id`
- `awaiting_input_from`
- `world_version`

These values are treated as state, not transient controller-only metadata.

## World Updates

World updates are deterministic and centralized.

- Agents do not directly mutate world state.
- The orchestrator is the only caller of the dispatcher.
- The dispatcher applies typed `WorldMutation` values and returns a new immutable `WorldState`.

This keeps world writes auditable and testable.

## Orchestrator Flow

`TableOrchestrator` runs a single-turn loop with these steps:

1. `waiting_for_intent`
2. `adjudicating`
3. `extracting`
4. `applying_mutations`
5. `turn_complete`

The orchestrator:

- reads the active actor from world state
- calls the adjudicator using a scoped world view (actor, current scene, nearby room connections, active objectives, recent log, relevant rules)
- waits on the same actor when a ruling still requires a player roll/check or clarification
- optionally calls the extractor
- applies mutations through the dispatcher
- advances turn metadata
- persists a snapshot at the end of the loop

## Snapshot Behavior

Snapshots are persisted under `artifacts/world_snapshots/`.

Filename pattern:

`session_<game_session_id>_loop_XXXX_turn_XXXX_v_XXXX_actor_<actor_id>.json`

Snapshots are written after each orchestrator loop and are used as the primary restore source.

## Loader Behavior

`AdventureLoader` is snapshot-first.

On load:

1. It looks for the latest snapshot.
2. If a `game_session_id` is provided, it restores the latest snapshot for that session.
3. If no matching snapshot exists, it creates a fresh world from `assets/`.

Fresh worlds get a short 5-character `game_session_id`.

## Snapshot Tooling

Snapshot inspection utilities live in `backend/orchestrator/snapshot_tools.py`.

Supported commands:

- `list`
- `diff`
- `diff-latest`

These tools are intended for quick inspection of persisted world evolution.

## REST API

The REST API wraps the orchestrator runtime and exposes turn advancement via HTTP POST requests.

### Endpoints

**POST `/api/advance`**

Process a player action and advance the game state.

Request body:
```json
{
  "actor": "aldric_stonehammer",
  "action": "I swing my sword at the goblin"
}
```

Response:
```json
{
  "success": true,
  "data": {
    "status": "approved",
    "ruling": "Aldric charges and slams the goblin for 9 damage.",
    "actor_id": "aldric_stonehammer",
    "awaiting_actor_id": "sylara_nightveil",
    "advanced_turn": true,
    "applied_mutation_count": 3
  },
  "error": null,
  "actor_id": "aldric_stonehammer"
}
```

The `action` string is processed by the Orchestrator through the Adjudicator/Extractor layers:
- **Questions**: "Do I still have a 2nd level spell slot?" (answered by adjudicator, does not advance turn)
- **Intents**: "I swing for the goblin with my sword" (approved + extracted, may advance turn)
- **Rejections**: Invalid or illegal actions (adjudicator rejects, does not advance turn)

Not all responses advance the turn. Questions and clarifications keep the turn on the same actor.

**GET `/api/rewind`**

Delete the latest persisted snapshot for the active session and restore the previous snapshot into the running orchestrator.

**GET `/api/status`**

Get current game state snapshot (session ID, active actor, world version, party members).

**GET `/health`**

Health check endpoint (returns `{"status": "ok"}`).

### Lifespan Management

The FastAPI app initializes the game engine on startup:
1. Loads world from snapshots (or creates fresh from assets)
2. Creates adjudicator and extractor agents
3. Initializes `TableOrchestrator` with turn order from party
4. Registers orchestrator with API routes

Orchestrator persists snapshots after each turn.

## Testing Notes

Main regression scripts:

- `python test_loader.py`
- `python test_orchestrator.py`
- `python test_snapshot_tools.py`
- `python test_agent_contracts.py`
- `python test_agents.py`

Because the loader restores snapshots by default, tests that touch loader/orchestrator behavior should use isolated temporary snapshot directories to avoid cross-test contamination.

## Documentation Rule

When tools or commands change:

1. Update `README.md`
2. Update this file if the architecture or runtime behavior changed
