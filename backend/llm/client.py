"""Azure OpenAI LLM client wrapper."""

import logging
import os
import time
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI, RateLimitError

logger = logging.getLogger(__name__)

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
        max_retries: int = 4,
        base_delay: float = 2.0,
    ) -> dict:
        """
        Call Azure OpenAI chat completion with exponential backoff on 429s.

        Args:
            messages: List of role/content dicts
            temperature: Sampling temperature
            max_tokens: Max response tokens
            max_retries: Maximum number of retry attempts on RateLimitError
            base_delay: Initial delay in seconds (doubles each retry, capped at 30s)

        Returns:
            Full completion response dict
        """
        attempt = 0
        delay = base_delay
        while True:
            try:
                return self.client.chat.completions.create(
                    model=self.deployment_name,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            except RateLimitError as exc:
                attempt += 1
                if attempt > max_retries:
                    logger.error(
                        "[LLMClient] Rate limit exceeded after %d retries: %s",
                        max_retries,
                        exc,
                    )
                    raise
                wait = min(delay, 30.0)
                logger.warning(
                    "[LLMClient] 429 capacity error — retrying in %.1fs (attempt %d/%d): %s",
                    wait,
                    attempt,
                    max_retries,
                    exc,
                )
                time.sleep(wait)
                delay *= 2
