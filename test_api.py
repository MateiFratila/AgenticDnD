"""Tests for REST API endpoints and integration with orchestrator."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from fastapi.testclient import TestClient

from backend.main import create_app
from backend.api.routes import set_orchestrator
from backend.agents import BaseAgent
from backend.orchestrator import TableOrchestrator
from backend.world import AdventureLoader


def test_api_initialization():
    """Test that FastAPI app initializes game engine on startup."""
    assets_dir = Path(__file__).parent / "assets"

    with TemporaryDirectory() as temp_dir:
        snapshot_dir = Path(temp_dir) / "snapshots"

        # Custom lifespan that uses temp snapshot dir
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def test_lifespan(app):
            loader = AdventureLoader(assets_dir, snapshot_dir=snapshot_dir)
            world = loader.load_adventure(
                adventure_file="adventure_sunken_grotto.json",
                pc_files=["pc_aldric_stonehammer.json", "pc_sylara_nightveil.json"],
                rules_file="homebrew_rules.json",
            )

            session_id = world.game_session_id
            adjudicator_agent = BaseAgent(
                agent_type="adjudicator", agent_name="Adjudicator"
            )
            extractor_agent = BaseAgent(
                agent_type="extractor", agent_name="Extractor"
            )

            turn_order = list(world.party.keys())
            orchestrator = TableOrchestrator.from_agents(
                world=world,
                turn_order=turn_order,
                adjudicator_agent=adjudicator_agent,
                extractor_agent=extractor_agent,
                snapshot_dir=snapshot_dir,
            )

            set_orchestrator(orchestrator, session_id)
            yield

        # Create app with test lifespan
        from fastapi import FastAPI

        app = FastAPI(lifespan=test_lifespan)
        from backend.api import router

        app.include_router(router)

        @app.get("/health")
        async def health():
            return {"status": "ok"}

        client = TestClient(app)

        # Test health check
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


def test_api_advance_approved():
    """Test POST /api/advance with an approved action."""
    assets_dir = Path(__file__).parent / "assets"

    with TemporaryDirectory() as temp_dir:
        snapshot_dir = Path(temp_dir) / "snapshots"

        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def test_lifespan(app):
            loader = AdventureLoader(assets_dir, snapshot_dir=snapshot_dir)
            world = loader.load_adventure(
                adventure_file="adventure_sunken_grotto.json",
                pc_files=["pc_aldric_stonehammer.json", "pc_sylara_nightveil.json"],
                rules_file="homebrew_rules.json",
            )

            session_id = world.game_session_id
            adjudicator_agent = BaseAgent(
                agent_type="adjudicator", agent_name="Adjudicator"
            )
            extractor_agent = BaseAgent(
                agent_type="extractor", agent_name="Extractor"
            )

            turn_order = list(world.party.keys())
            orchestrator = TableOrchestrator.from_agents(
                world=world,
                turn_order=turn_order,
                adjudicator_agent=adjudicator_agent,
                extractor_agent=extractor_agent,
                snapshot_dir=snapshot_dir,
            )

            set_orchestrator(orchestrator, session_id)
            yield

        from fastapi import FastAPI

        app = FastAPI(lifespan=test_lifespan)
        from backend.api import router

        app.include_router(router)

        client = TestClient(app)

        # Get initial status
        status_response = client.get("/api/status")
        assert status_response.status_code == 200
        initial_status = status_response.json()
        first_actor = initial_status["active_actor_id"]

        # Post an action
        action_request = {
            "actor": first_actor,
            "action": "I attack the nearest enemy",
        }

        response = client.post("/api/advance", json=action_request)
        assert response.status_code == 200

        data = response.json()
        assert data["success"] is True
        assert data["actor_id"] == first_actor
        assert data["data"] is not None
        assert "status" in data["data"]
        assert "ruling" in data["data"]
        assert "awaiting_actor_id" in data["data"]


def test_api_advance_wrong_actor():
    """Test that /api/advance rejects action from non-active actor."""
    assets_dir = Path(__file__).parent / "assets"

    with TemporaryDirectory() as temp_dir:
        snapshot_dir = Path(temp_dir) / "snapshots"

        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def test_lifespan(app):
            loader = AdventureLoader(assets_dir, snapshot_dir=snapshot_dir)
            world = loader.load_adventure(
                adventure_file="adventure_sunken_grotto.json",
                pc_files=["pc_aldric_stonehammer.json", "pc_sylara_nightveil.json"],
                rules_file="homebrew_rules.json",
            )

            session_id = world.game_session_id
            adjudicator_agent = BaseAgent(
                agent_type="adjudicator", agent_name="Adjudicator"
            )
            extractor_agent = BaseAgent(
                agent_type="extractor", agent_name="Extractor"
            )

            turn_order = list(world.party.keys())
            orchestrator = TableOrchestrator.from_agents(
                world=world,
                turn_order=turn_order,
                adjudicator_agent=adjudicator_agent,
                extractor_agent=extractor_agent,
                snapshot_dir=snapshot_dir,
            )

            set_orchestrator(orchestrator, session_id)
            yield

        from fastapi import FastAPI

        app = FastAPI(lifespan=test_lifespan)
        from backend.api import router

        app.include_router(router)

        client = TestClient(app)

        # Get initial status to find first and second actor
        status_response = client.get("/api/status")
        initial_status = status_response.json()
        first_actor = initial_status["active_actor_id"]
        party_members = initial_status["party_members"]
        wrong_actor = next(p for p in party_members if p != first_actor)

        # Try to act as wrong actor
        action_request = {
            "actor": wrong_actor,
            "action": "I attack the nearest enemy",
        }

        response = client.post("/api/advance", json=action_request)
        assert response.status_code == 200

        data = response.json()
        assert data["success"] is False
        assert "not" in data["error"].lower()
        assert wrong_actor in data["error"]


def test_api_status():
    """Test GET /api/status endpoint."""
    assets_dir = Path(__file__).parent / "assets"

    with TemporaryDirectory() as temp_dir:
        snapshot_dir = Path(temp_dir) / "snapshots"

        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def test_lifespan(app):
            loader = AdventureLoader(assets_dir, snapshot_dir=snapshot_dir)
            world = loader.load_adventure(
                adventure_file="adventure_sunken_grotto.json",
                pc_files=["pc_aldric_stonehammer.json", "pc_sylara_nightveil.json"],
                rules_file="homebrew_rules.json",
            )

            session_id = world.game_session_id
            adjudicator_agent = BaseAgent(
                agent_type="adjudicator", agent_name="Adjudicator"
            )
            extractor_agent = BaseAgent(
                agent_type="extractor", agent_name="Extractor"
            )

            turn_order = list(world.party.keys())
            orchestrator = TableOrchestrator.from_agents(
                world=world,
                turn_order=turn_order,
                adjudicator_agent=adjudicator_agent,
                extractor_agent=extractor_agent,
                snapshot_dir=snapshot_dir,
            )

            set_orchestrator(orchestrator, session_id)
            yield

        from fastapi import FastAPI

        app = FastAPI(lifespan=test_lifespan)
        from backend.api import router

        app.include_router(router)

        client = TestClient(app)

        response = client.get("/api/status")
        assert response.status_code == 200

        data = response.json()
        assert data["success"] is True
        assert "session_id" in data
        assert "active_actor_id" in data
        assert "awaiting_input_from" in data
        assert "world_version" in data
        assert "party_size" in data
        assert data["party_size"] == 2
        assert "party_members" in data


def test_api_init_resets_and_kicks_off(monkeypatch):
    """Test POST /api/init clears snapshots, reinitializes world, and triggers kickoff."""
    from backend.api import routes

    app = create_app()
    client = TestClient(app)

    with TemporaryDirectory() as temp_dir:
        snapshot_dir = Path(temp_dir) / "snapshots"
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        (snapshot_dir / "session_old_loop_0001_turn_0000_v_0000_actor_init.json").write_text("{}")

        fake_world = SimpleNamespace(
            game_session_id="abcde",
            active_actor_id="aldric_stonehammer",
            awaiting_input_from="sylara_nightveil",
            world_version=1,
            turn_count=1,
            party={"aldric_stonehammer": object(), "sylara_nightveil": object()},
        )

        fake_kickoff = SimpleNamespace(
            status="approved",
            ruling="The adventure begins at the flooded cavern entrance.",
            actor_id="aldric_stonehammer",
            awaiting_actor_id="sylara_nightveil",
            advanced_turn=True,
            applied_mutation_count=1,
        )

        class StubOrchestrator:
            def __init__(self):
                self.world = fake_world
                self.kickoff_action = None

            def process_intent(self, action_text: str):
                self.kickoff_action = action_text
                return fake_kickoff

        stub_orchestrator = StubOrchestrator()

        monkeypatch.setattr(routes, "_snapshot_dir", lambda: snapshot_dir)
        monkeypatch.setattr(routes, "_build_fresh_orchestrator", lambda _: stub_orchestrator)

        response = client.post("/init")
        assert response.status_code == 200

        data = response.json()
        assert data["success"] is True
        assert data["session_id"] == "abcde"
        assert data["deleted_snapshots"] == 1
        assert data["kickoff"]["status"] == "approved"
        assert "Adventure Start" in stub_orchestrator.kickoff_action

        assert not any(snapshot_dir.glob("*loop_*.json"))


def test_api_rewind_deletes_latest_snapshot_and_reloads_previous(monkeypatch):
    """GET /api/rewind should drop the latest snapshot and restore the previous one."""
    from backend.api import routes
    from fastapi import FastAPI
    import os
    import time

    app = FastAPI()
    from backend.api import router

    app.include_router(router)
    client = TestClient(app)

    with TemporaryDirectory() as temp_dir:
        snapshot_dir = Path(temp_dir) / "snapshots"
        snapshot_dir.mkdir(parents=True, exist_ok=True)

        older_snapshot = snapshot_dir / "session_abcde_loop_0001_turn_0000_v_0000_actor_init.json"
        latest_snapshot = snapshot_dir / "session_abcde_loop_0002_turn_0001_v_0001_actor_test.json"
        older_snapshot.write_text("{}", encoding="utf-8")
        latest_snapshot.write_text("{}", encoding="utf-8")

        now = time.time()
        os.utime(older_snapshot, (now - 10, now - 10))
        os.utime(latest_snapshot, (now, now))

        current_world = SimpleNamespace(
            game_session_id="abcde",
            active_actor_id="aldric_stonehammer",
            awaiting_input_from="aldric_stonehammer",
            world_version=1,
            turn_count=1,
            party={"aldric_stonehammer": object(), "sylara_nightveil": object()},
        )
        restored_world = SimpleNamespace(
            game_session_id="abcde",
            active_actor_id="sylara_nightveil",
            awaiting_input_from="sylara_nightveil",
            world_version=0,
            turn_count=0,
            party={"aldric_stonehammer": object(), "sylara_nightveil": object()},
        )

        current_orchestrator = SimpleNamespace(world=current_world)
        restored_orchestrator = SimpleNamespace(world=restored_world)

        monkeypatch.setattr(routes, "_snapshot_dir", lambda: snapshot_dir)
        monkeypatch.setattr(
            routes,
            "_build_fresh_orchestrator",
            lambda _, game_session_id=None: restored_orchestrator,
        )

        set_orchestrator(current_orchestrator, "abcde")

        response = client.get("/api/rewind")
        assert response.status_code == 200

        data = response.json()
        assert data["success"] is True
        assert data["deleted_snapshot"] == latest_snapshot.name
        assert data["restored_from_snapshot"] == older_snapshot.name
        assert data["session_id"] == "abcde"
        assert latest_snapshot.exists() is False
        assert routes.get_orchestrator() is restored_orchestrator


def test_api_snapshot_list_endpoint(monkeypatch):
    """GET /api/snapshots should expose the current session snapshot list over HTTP."""
    from backend.api import routes
    from fastapi import FastAPI

    app = FastAPI()
    from backend.api import router

    app.include_router(router)
    client = TestClient(app)

    with TemporaryDirectory() as temp_dir:
        snapshot_dir = Path(temp_dir) / "snapshots"
        snapshot_dir.mkdir(parents=True, exist_ok=True)

        first = snapshot_dir / "session_abcde_loop_0001_turn_0000_v_0000_actor_init.json"
        second = snapshot_dir / "session_abcde_loop_0002_turn_0001_v_0001_actor_test.json"
        first.write_text("{}", encoding="utf-8")
        second.write_text("{}", encoding="utf-8")

        monkeypatch.setattr(routes, "_snapshot_dir", lambda: snapshot_dir)
        set_orchestrator(SimpleNamespace(world=SimpleNamespace(game_session_id="abcde")), "abcde")

        response = client.get("/api/snapshots")
        assert response.status_code == 200

        data = response.json()
        assert data["success"] is True
        assert data["session_id"] == "abcde"
        assert data["snapshot_count"] == 2
        assert {Path(name).name for name in data["snapshots"]} == {first.name, second.name}


def test_api_snapshot_diff_latest_endpoint(monkeypatch):
    """GET /api/snapshots/diff-latest should diff the newest two session snapshots over HTTP."""
    from backend.api import routes
    from fastapi import FastAPI
    import os
    import time

    app = FastAPI()
    from backend.api import router

    app.include_router(router)
    client = TestClient(app)

    with TemporaryDirectory() as temp_dir:
        snapshot_dir = Path(temp_dir) / "snapshots"
        snapshot_dir.mkdir(parents=True, exist_ok=True)

        older = snapshot_dir / "session_abcde_loop_0001_turn_0000_v_0000_actor_init.json"
        newer = snapshot_dir / "session_abcde_loop_0002_turn_0001_v_0001_actor_test.json"
        older.write_text(json.dumps({"turn_count": 0}), encoding="utf-8")
        newer.write_text(json.dumps({"turn_count": 1}), encoding="utf-8")

        now = time.time()
        os.utime(older, (now - 10, now - 10))
        os.utime(newer, (now, now))

        monkeypatch.setattr(routes, "_snapshot_dir", lambda: snapshot_dir)
        set_orchestrator(SimpleNamespace(world=SimpleNamespace(game_session_id="abcde")), "abcde")

        response = client.get("/api/snapshots/diff-latest")
        assert response.status_code == 200

        data = response.json()
        assert data["success"] is True
        assert data["session_id"] == "abcde"
        assert data["old_snapshot"] == older.name
        assert data["new_snapshot"] == newer.name
        assert any("~ turn_count" in line for line in data["diffs"])
