"""Base agent class with LLM integration and structured logging."""

import json
import logging
from abc import ABC
from typing import Optional

from backend.llm.client import LLMClient
from backend.llm.prompts import PromptLoader
from .contracts import parse_adjudicator_response, parse_extractor_response


logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    """Base agent class with LLM integration and structured logging."""

    def __init__(
        self,
        agent_type: str,
        agent_name: str = "Agent",
        temperature: float = 0.7,
        max_tokens: int = 2000,
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

        self.llm_client = LLMClient()
        self.prompt_loader = PromptLoader()

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
        response = self.llm_client.chat_completion(
            messages=messages,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )

        # Log response
        choice = response.choices[0]
        response_log = {
            "agent": self.agent_name,
            "finish_reason": choice.finish_reason,
            "response_length": len(choice.message.content),
            "usage": {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            },
        }
        logger.info(f"[{self.agent_name}] LLM Response: {json.dumps(response_log)}")

        return {
            "content": choice.message.content,
            "finish_reason": choice.finish_reason,
            "usage": {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            },
        }

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
        raw = self.think(
            system_prompt=system_prompt,
            user_input=user_input,
            prompt_name=prompt_name,
        )
        return parse_adjudicator_response(raw)

    def think_extraction(
        self,
        user_input: str,
        system_prompt: Optional[str] = None,
        prompt_name: str = "system",
    ):
        """Call LLM and return validated extractor response model."""
        raw = self.think(
            system_prompt=system_prompt,
            user_input=user_input,
            prompt_name=prompt_name,
        )
        return parse_extractor_response(raw)
