"""Prompt loader for agent-specific prompt templates."""

from pathlib import Path
from typing import Optional


class PromptLoader:
    """Loads prompts from filesystem organized by agent type."""

    def __init__(self, prompts_dir: Optional[Path] = None):
        """
        Initialize prompt loader.

        Args:
            prompts_dir: Root directory for prompts. Defaults to backend/prompts/
        """
        if prompts_dir is None:
            prompts_dir = Path(__file__).parent.parent / "prompts"
        self.prompts_dir = Path(prompts_dir)

    def load_prompt(self, agent_type: str, prompt_name: str = "system") -> str:
        """
        Load a prompt by agent type and name.

        Looks for: prompts/{agent_type}/{prompt_name}.md or .txt

        Args:
            agent_type: Agent type directory (e.g., "adjudicator", "extractor")
            prompt_name: Prompt filename without extension (default: "system")

        Returns:
            Prompt text content
        """
        agent_dir = self.prompts_dir / agent_type
        if not agent_dir.exists():
            raise FileNotFoundError(f"Agent prompt directory not found: {agent_dir}")

        # Try .md first, then .txt
        for ext in [".md", ".txt"]:
            filepath = agent_dir / f"{prompt_name}{ext}"
            if filepath.exists():
                return filepath.read_text()

        raise FileNotFoundError(
            f"Prompt not found: {agent_type}/{prompt_name}. "
            f"Looked in {agent_dir}"
        )

    def load_all_prompts(self, agent_type: str) -> dict[str, str]:
        """Load all prompts for an agent type."""
        agent_dir = self.prompts_dir / agent_type
        prompts = {}
        for filepath in agent_dir.glob("*.[mt][dx][t]"):
            name = filepath.stem
            prompts[name] = filepath.read_text()
        return prompts
