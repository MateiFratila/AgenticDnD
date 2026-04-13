"""Main FastAPI application with lifespan management and table initialization."""

from contextlib import asynccontextmanager
from pathlib import Path
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.agents import BaseAgent
from backend.api import router
from backend.api.routes import init_game, set_orchestrator
from backend.orchestrator import TableOrchestrator
from backend.world import AdventureLoader


logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize game engine on startup, clean up on shutdown."""
    logger.info("[APP] Initializing game engine...")

    try:
        # Load adventure from snapshots or assets
        assets_dir = Path(__file__).parent.parent / "assets"
        loader = AdventureLoader(assets_dir)

        world = loader.load_adventure(
            adventure_file="adventure_sunken_grotto.json",
            pc_files=["pc_aldric_stonehammer.json", "pc_sylara_nightveil.json"],
            rules_file="homebrew_rules.json",
        )

        session_id = world.game_session_id
        logger.info("[APP] Loaded world | session_id=%s", session_id)

        # Create adjudicator and extractor agents
        adjudicator_agent = BaseAgent(
            agent_type="adjudicator",
            agent_name="Adjudicator",
        )

        extractor_agent = BaseAgent(
            agent_type="extractor",
            agent_name="Extractor",
            temperature=0.2,
        )
        intent_agent = BaseAgent(
            agent_type="intent",
            agent_name="Intent Generator",
        )

        # Create orchestrator from agents
        turn_order = list(world.party.keys())
        orchestrator = TableOrchestrator.from_agents(
            world=world,
            turn_order=turn_order,
            adjudicator_agent=adjudicator_agent,
            extractor_agent=extractor_agent,
            intent_agent=intent_agent,
        )

        # Register orchestrator with routes
        set_orchestrator(orchestrator, session_id)

        logger.info(
            "[APP] Table orchestrator initialized | turn_order=%s | first_actor=%s",
            turn_order,
            orchestrator.current_actor_id,
        )

        yield

    except Exception as e:
        logger.error("[APP] Failed to initialize game engine: %s", str(e), exc_info=True)
        raise

    finally:
        logger.info("[APP] Shutting down game engine")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="Agentic DnD API",
        description="Turn-based D&D simulation with LLM adjudication",
        version="1.0.0",
        lifespan=lifespan,
    )

    # CORS middleware (allow localhost for development)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["localhost", "127.0.0.1"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include API routes
    app.include_router(router)

    # Health check endpoint
    @app.get("/health")
    async def health():
        return {"status": "ok"}

    # Root-level alias for game reset/start endpoint.
    @app.post("/init")
    async def init():
        return await init_game()

    return app


# Create the application instance
app = create_app()
