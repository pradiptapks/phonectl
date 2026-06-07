"""AI provider interface and registry — base classes for all AI backends.

The registry tries providers in order: Ollama (local) -> Claude (MCP) -> Gemini -> fallback.
If no AI provider is available, phonectl falls back to the rule-based diagnostic engine.

This module defines the interface only. Providers are implemented as stubs for future use.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from phonectl.core.device import DeviceInfo


@dataclass
class DeviceContext:
    """Device context sent to AI providers for analysis.

    Contains only non-PII device properties — never serial numbers,
    IMEI, accounts, or personal data.
    """
    manufacturer: str = ""
    model: str = ""
    codename: str = ""
    android_version: str = ""
    security_patch: str = ""
    vndk_version: str = ""
    kernel_version: str = ""
    ram_total_mb: int = 0
    storage_free_gb: float = 0.0
    cpu_abi: str = ""
    security_score: int = 0
    health_score: int = 0
    findings: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)

    @classmethod
    def from_device_info(cls, info: DeviceInfo, **kwargs) -> DeviceContext:
        return cls(
            manufacturer=info.manufacturer,
            model=info.model,
            codename=info.codename,
            android_version=info.android_version,
            security_patch=info.security_patch,
            vndk_version=info.vndk_version,
            kernel_version=info.kernel_version,
            ram_total_mb=info.ram_total_mb,
            storage_free_gb=info.storage_free_gb,
            cpu_abi=info.cpu_abi,
            **kwargs,
        )


class AIProvider(ABC):
    """Abstract base class for AI backends — local or cloud.

    Implementations:
    - OllamaProvider: local LLM via localhost:11434 (free, private)
    - ClaudeProvider: Claude via Cursor SDK or MCP (requires Cursor)
    - GeminiProvider: Google Gemini free tier API (future)
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider display name."""

    @abstractmethod
    def is_available(self) -> bool:
        """Check if this provider is accessible (server running, API key set, etc.)."""

    @abstractmethod
    def analyze(self, context: DeviceContext) -> str:
        """Send device context and get an analysis/recommendation string."""

    @abstractmethod
    def troubleshoot(self, context: DeviceContext, question: str) -> str:
        """Answer a troubleshooting question about the device."""


class AIProviderRegistry:
    """Try AI providers in priority order, fall back to rule-based if none available.

    Priority: Ollama (local) -> Claude (MCP) -> rule-based fallback.
    """

    def __init__(self):
        self._providers: list[AIProvider] = []

    def register(self, provider: AIProvider) -> None:
        self._providers.append(provider)

    def get_provider(self) -> AIProvider | None:
        """Return the first available provider, or None."""
        for provider in self._providers:
            try:
                if provider.is_available():
                    return provider
            except Exception:
                continue
        return None

    def get_all_status(self) -> list[dict]:
        """Return availability status of all registered providers."""
        status = []
        for p in self._providers:
            try:
                available = p.is_available()
            except Exception:
                available = False
            status.append({"name": p.name, "available": available})
        return status
