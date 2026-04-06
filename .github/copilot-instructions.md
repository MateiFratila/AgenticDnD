# Project Guidelines

## Code Style
- Target Python 3.11.
- Prefer explicit type hints and small, readable async functions.
- Keep world-state updates deterministic and centralized in the world engine.

## Architecture
- Backend lives under `backend/` with clear module boundaries:
  - `world/`: deterministic game state and rules
  - `agents/`: agent loop and concrete agents
  - `memory/`: vector memory abstraction (ChromaDB)
  - `tools/`: tool call schemas and allowed agent actions
  - `orchestrator/`: turn-based simulation loop
  - `llm/`: OpenAI wrapper for tool selection
- Agents can propose actions only; only the DM applies updates to world state.

## Build And Test
- Create and activate a virtual environment, then install dependencies:
  - `python3.11 -m venv .venv`
  - `source .venv/bin/activate`
  - `pip install -r backend/requirements.txt`
- Run simulation:
  - `python -m backend.main --simulate --turns 8`
- Run API server:
  - `uvicorn backend.main:app --reload`

## Conventions
- Log turn activity with clear prefixes (`[AGENT]`, `[MEMORY]`, `[DM]`, `[WORLD]`).
- Keep tool interfaces stable and serializable (Pydantic models).
- For world-state schema, payload-scoping, turn-history, or trace-metadata changes, consult the `world-state` skill in `.github/skills/world-state/SKILL.md`.
- Handle missing OpenAI credentials gracefully with deterministic fallback behavior.