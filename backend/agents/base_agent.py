"""Base agent class with LLM integration and structured logging."""

import json
import logging
import re
from abc import ABC
from pathlib import Path
from typing import Optional

from backend.llm.client import LLMClient
from backend.llm.prompts import PromptLoader
from .contracts import (
    AdjudicatorResponse,
    DestinationRoute,
    ExtractorMutation,
    ExtractorResponse,
    parse_adjudicator_response,
    parse_extractor_response,
)
from backend.world.mutations import MutationType


logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    """Base agent class with LLM integration and structured logging."""

    def __init__(
        self,
        agent_type: str,
        agent_name: str = "Agent",
        temperature: float = 0.7,
        max_tokens: int = 6000,
    ):
        """
        Initialize base agent.

        Args:
            agent_type: Type of agent (e.g., "adjudicator", "extractor")
            agent_name: Human-readable agent name for logging
            temperature: LLM sampling temperature
            max_tokens: Max response tokens
        """
        self.agent_type = agent_type
        self.agent_name = agent_name
        self.temperature = temperature
        self.max_tokens = max_tokens
        self._llm_trace_dir = Path(__file__).parent.parent.parent / "artifacts" / "llm_traces"

        self.llm_client = LLMClient()
        self.prompt_loader = PromptLoader()

    @staticmethod
    def _sanitize_token(value: object, fallback: str = "unknown") -> str:
        """Convert arbitrary value into a filesystem-safe token."""
        if value is None:
            return fallback
        token = re.sub(r"[^a-zA-Z0-9_-]+", "_", str(value).strip())
        token = token.strip("_")
        return token or fallback

    def _build_trace_file_path(self, prompt_name: str, user_input: str) -> Path:
        """Build a short trace file path: s_<nr>_t_<nr>_a_<agent>.json."""
        session_id = "unknown"
        turn_count = "unknown"

        try:
            payload = json.loads(user_input)
            world_state = payload.get("world_state", {}) if isinstance(payload, dict) else {}
            world_state = world_state if isinstance(world_state, dict) else {}
            session = world_state.get("session", {})
            session = session if isinstance(session, dict) else {}

            raw_session_id = world_state.get("game_session_id") or session.get("game_session_id")
            session_id = self._sanitize_token(raw_session_id)

            raw_turn = world_state.get("turn_count")
            if raw_turn is None:
                raw_turn = session.get("turn_count")

            if isinstance(raw_turn, int):
                turn_count = f"{raw_turn:04d}"
            elif isinstance(raw_turn, str) and raw_turn.isdigit():
                turn_count = f"{int(raw_turn):04d}"
        except Exception:
            # Non-JSON payloads still produce a stable fallback filename.
            pass

        agent = self._sanitize_token(self.agent_type)
        return self._llm_trace_dir / f"s_{session_id}_t_{turn_count}_a_{agent}.json"

    def _persist_llm_trace(
        self,
        prompt_name: str,
        messages: list[dict],
        user_input: str,
        response_content: Optional[str] = None,
        finish_reason: Optional[str] = None,
        usage: Optional[dict] = None,
        error: Optional[str] = None,
    ) -> None:
        """Persist LLM request/response payload for offline debugging."""
        try:
            self._llm_trace_dir.mkdir(parents=True, exist_ok=True)
            trace_file = self._build_trace_file_path(prompt_name=prompt_name, user_input=user_input)

            trace = {
                "agent_name": self.agent_name,
                "agent_type": self.agent_type,
                "prompt_name": prompt_name,
                "model": self.llm_client.deployment_name,
                "request": {
                    "temperature": self.temperature,
                    "max_tokens": self.max_tokens,
                    "messages": messages,
                    "user_input_length": len(user_input),
                },
                "response": {
                    "content": response_content,
                    "finish_reason": finish_reason,
                    "usage": usage,
                },
                "error": error,
            }
            trace_file.write_text(json.dumps(trace, indent=2), encoding="utf-8")
            logger.info("[%s] LLM trace persisted | path=%s", self.agent_name, trace_file)
        except Exception as exc:
            logger.warning(
                "[%s] Failed to persist LLM trace file: %s",
                self.agent_name,
                str(exc),
            )

    def _load_system_prompt(self, prompt_name: str = "system") -> str:
        """Load system prompt from prompts/{agent_type}/{prompt_name}.md"""
        return self.prompt_loader.load_prompt(self.agent_type, prompt_name)

    def _call_llm(
        self,
        system_prompt: str,
        user_input: str,
        prompt_name: str = "system",
    ) -> dict:
        """
        Call LLM with structured logging of payload and response.

        Args:
            system_prompt: System prompt text
            user_input: User message text
            prompt_name: Name of the prompt being used (for logging)

        Returns:
            LLM response dict with choice, tokens, etc.
        """
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_input},
        ]

        # Log request payload
        request_log = {
            "agent": self.agent_name,
            "agent_type": self.agent_type,
            "prompt_name": prompt_name,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "message_count": len(messages),
            "system_prompt_length": len(system_prompt),
            "user_input_length": len(user_input),
        }
        logger.info(f"[{self.agent_name}] LLM Request: {json.dumps(request_log)}")

        # Call LLM
        try:
            response = self.llm_client.chat_completion(
                messages=messages,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )
        except Exception as exc:
            self._persist_llm_trace(
                prompt_name=prompt_name,
                messages=messages,
                user_input=user_input,
                error=str(exc),
            )
            raise

        # Log response
        choice = response.choices[0]
        content = choice.message.content or ""

        response_log = {
            "agent": self.agent_name,
            "finish_reason": choice.finish_reason,
            "response_length": len(content),
            "usage": {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            },
        }
        logger.info(f"[{self.agent_name}] LLM Response: {json.dumps(response_log)}")

        self._persist_llm_trace(
            prompt_name=prompt_name,
            messages=messages,
            user_input=user_input,
            response_content=content,
            finish_reason=choice.finish_reason,
            usage={
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            },
        )

        return {
            "content": content,
            "finish_reason": choice.finish_reason,
            "usage": {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            },
        }

    @staticmethod
    def _fallback_adjudicator_response() -> AdjudicatorResponse:
        """Deterministic adjudicator fallback used when LLM output is unavailable."""
        return AdjudicatorResponse(
            status="approved",
            ruling=(
                "Adventure Start: The party gathers at the flooded cavern mouth as "
                "waves echo through stone and a first objective emerges."
            ),
            destination=[
                DestinationRoute(
                    actor="extractor",
                    purpose="Commit opening-scene state updates",
                    payload_hint="Apply start-of-adventure log/turn mutations",
                )
            ],
            reasoning="Deterministic fallback response applied due to unavailable/invalid LLM output.",
            suggested_alternatives=[],
        )

    @staticmethod
    def _fallback_extractor_response() -> ExtractorResponse:
        """Deterministic extractor fallback used when LLM output is unavailable."""
        return ExtractorResponse(
            root=[
                ExtractorMutation(
                    type=MutationType.APPEND_LOG_ENTRY,
                    entry="[DM] Adventure Start fallback applied: opening scene established.",
                ),
                ExtractorMutation(
                    type=MutationType.INCREMENT_TURN,
                ),
            ]
        )

    def think(
        self,
        system_prompt: Optional[str] = None,
        user_input: str = "",
        prompt_name: str = "system",
    ) -> str:
        """
        Call LLM and return response text.

        Args:
            system_prompt: System prompt. If None, loads from prompts/{agent_type}/system.md
            user_input: User message
            prompt_name: Prompt name for logging and auto-load

        Returns:
            Response content string
        """
        if system_prompt is None:
            system_prompt = self._load_system_prompt(prompt_name)

        response = self._call_llm(
            system_prompt=system_prompt,
            user_input=user_input,
            prompt_name=prompt_name,
        )
        return response["content"]

    def think_adjudication(
        self,
        user_input: str,
        system_prompt: Optional[str] = None,
        prompt_name: str = "system",
    ):
        """Call LLM and return validated adjudicator response model."""
        try:
            raw = self.think(
                system_prompt=system_prompt,
                user_input=user_input,
                prompt_name=prompt_name,
            )
            if not raw.strip():
                raise ValueError("Empty adjudicator response")
            return parse_adjudicator_response(raw)
        except Exception as exc:
            logger.warning(
                "[%s] Falling back to deterministic adjudicator response: %s",
                self.agent_name,
                str(exc),
            )
            return self._fallback_adjudicator_response()

    def think_extraction(
        self,
        user_input: str,
        system_prompt: Optional[str] = None,
        prompt_name: str = "system",
    ):
        """Call LLM and return validated extractor response model."""
        try:
            raw = self.think(
                system_prompt=system_prompt,
                user_input=user_input,
                prompt_name=prompt_name,
            )
            if not raw.strip():
                raise ValueError("Empty extractor response")
            return parse_extractor_response(raw)
        except Exception as exc:
            logger.warning(
                "[%s] Falling back to deterministic extractor response: %s",
                self.agent_name,
                str(exc),
            )
            return self._fallback_extractor_response()
