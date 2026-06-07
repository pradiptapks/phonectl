"""Ollama AI provider — local LLM for device analysis and troubleshooting.

Connects to Ollama running on localhost:11434. Completely free, private,
and offline. Requires the user to install Ollama and pull a model.

Setup:
    curl -fsSL https://ollama.com/install.sh | sh
    ollama pull llama3.2:3b    # or phi3, gemma2, etc.

Status: STUB — interface defined, implementation for future use.
"""

from __future__ import annotations

from phonectl.ai.base import AIProvider, DeviceContext

OLLAMA_URL = "http://localhost:11434"
DEFAULT_MODEL = "llama3.2:3b"

SYSTEM_PROMPT = """You are phonectl AI assistant — an expert in Android device 
management, security, and troubleshooting. You analyze device properties and 
provide specific, actionable recommendations. Always reference phonectl commands 
when suggesting fixes. Be concise."""


class OllamaProvider(AIProvider):
    """Local Ollama LLM provider.

    Not yet implemented — this is a stub defining the interface.
    When implemented, will connect to Ollama's REST API at localhost:11434.
    """

    def __init__(self, model: str = DEFAULT_MODEL, base_url: str = OLLAMA_URL):
        self.model = model
        self.base_url = base_url

    @property
    def name(self) -> str:
        return f"Ollama ({self.model})"

    def is_available(self) -> bool:
        """Check if Ollama is running locally."""
        try:
            import requests
            resp = requests.get(f"{self.base_url}/api/tags", timeout=2)
            return resp.status_code == 200
        except Exception:
            return False

    def analyze(self, context: DeviceContext) -> str:
        """Send device context to Ollama for analysis."""
        raise NotImplementedError(
            "Ollama provider not yet implemented. "
            "Install Ollama and contribute the implementation. "
            "See phonectl/ai/ollama.py for the interface."
        )

    def troubleshoot(self, context: DeviceContext, question: str) -> str:
        """Ask Ollama a troubleshooting question."""
        raise NotImplementedError(
            "Ollama provider not yet implemented. "
            "phonectl falls back to the rule-based diagnostic engine."
        )

    # Future implementation would use:
    # POST http://localhost:11434/api/generate
    # {"model": "llama3.2:3b", "system": SYSTEM_PROMPT, "prompt": "...", "stream": false}
