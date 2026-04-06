---
name: world-state
description: 'Design and maintain D&D world state, scoped adjudicator payloads, turn-log history, snapshot/trace naming, and token-budget-safe context shaping. Use when changing `WorldState`, `turn_log`, orchestrator payloads, session metadata, or debugging token-limit/state-history regressions.'
argument-hint: 'Describe the world-state change or bug, the relevant files, desired invariants, and any token-budget constraints.'
user-invocable: true
---

# World State

## Purpose
Use this skill when changing how game state is stored, summarized, logged, restored, or passed into the LLM layers.

The goal is to keep the simulation:
- deterministic
- auditable
- token-efficient
- easy to restore from snapshots

## Core Invariants
1. `WorldState` is the single source of truth for both game state and session state.
2. Agents may **propose** actions; only the orchestrator/dispatcher path may commit mutations.
3. Adjudicator prompts should receive a **scoped world view**, not a full raw dump, unless a full dump is strictly required.
4. `turn_log` should preserve **DM-facing history** needed for future adjudication; `[WORLD]` entries may additionally capture canonical state-change audit details.
5. Snapshot and trace filenames must derive from real session metadata (`game_session_id`, `turn_count`, `world_version`) rather than inferred or duplicated constants.
6. When token pressure rises, **reduce prompt scope first** before increasing `max_tokens`.

## Relevant Files
- `backend/world/state.py` — immutable source-of-truth models
- `backend/world/dispatcher.py` — deterministic mutation application
- `backend/world/loader.py` — snapshot-first restore/bootstrap
- `backend/orchestrator/table_orchestrator.py` — scoped payload building, turn flow, history logging
- `backend/agents/base_agent.py` — LLM calls, trace persistence, metadata extraction
- `test_orchestrator.py`, `test_payload_fix.py`, `test_agents.py`, `test_loader.py`

## Working Rules

### 1) State changes
- Prefer explicit typed mutations over implicit side effects.
- Keep world updates centralized in the dispatcher.
- Do not add test-only production hooks.

### 2) Prompt shaping
- Include only the actor, current scene, active objectives, recent history, and relevant rules when building adjudicator context.
- Avoid sending distant NPCs, inactive encounters, or large static blobs unless directly needed.
- Preserve enough context for legality/ruling decisions, but not more.

### 3) History and memory
- The adjudicator needs concise prior rulings in `turn_log` to reason about continuity.
- Keep only the recent slice in LLM payloads, but persist the full history in `WorldState` snapshots.
- Prefer compact structured prefixes such as `[DM][approved][actor_id]` and `[WORLD]`.

### 4) Traces and debugging
- If trace filenames show `unknown`, inspect the payload shape first.
- For scoped payloads, session metadata may live under `world_state.session.*`.
- Persist LLM traces and snapshots for debugging, but keep prompt payloads lean.

## Known Repo Solutions
- **Scoped adjudicator payload**: reduced prompt size by replacing the full `asdict(world)` dump with a decision-ready world view.
- **Trace filename fix**: read session/turn metadata from both top-level `world_state.*` and nested `world_state.session.*` fields.
- **Turn history fix**: record adjudicator rulings in `world.turn_log` so later turns retain DM context.

## Suggested Workflow
1. Reproduce the issue using the latest trace or snapshot.
2. Identify whether the root cause is:
   - state shape
   - mutation application
   - payload scope
   - history logging
   - snapshot/trace metadata
3. Add or update a regression test first.
4. Implement the smallest deterministic fix.
5. Verify with the relevant scripts:
   - `python test_orchestrator.py`
   - `python test_payload_fix.py`
   - `python test_agents.py`
   - `python test_loader.py`

## Anti-Patterns to Avoid
- Dumping the entire world state into every adjudicator call by default
- Treating extractor log lines as a substitute for DM history
- Duplicating state in ad hoc controller variables instead of `WorldState`
- Fixing token issues only by raising limits without reducing payload size first
- Logging ambiguous history without actor/status context
