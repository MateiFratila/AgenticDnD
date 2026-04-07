"""Azure OpenAI LLM client wrapper."""

import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

# Load .env from project root (two levels up from this file)
load_dotenv(Path(__file__).parent.parent.parent / ".env")


class LLMClient:
    """Manages Azure OpenAI API connection and calls."""

    def __init__(self):
        """Initialize Azure OpenAI client from environment variables."""
        endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
        api_key = os.getenv("AZURE_OPENAI_API_KEY")
        self.deployment_name = os.getenv("AZURE_OPENAI_DEPLOYMENT")

        self.api_key_set = bool(api_key)
        if not api_key:
            # Fall back to placeholder; actual calls will fail with helpful error
            api_key = "placeholder-key-not-set"

        self.client = OpenAI(base_url=endpoint, api_key=api_key)

    def chat_completion(
        self,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 6000,
    ) -> dict:
        """
        Call Azure OpenAI chat completion.

        Args:
            messages: List of role/content dicts
            temperature: Sampling temperature
            max_tokens: Max response tokens

        Returns:
            Full completion response dict
        """
        return self.client.chat.completions.create(
            model=self.deployment_name,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
