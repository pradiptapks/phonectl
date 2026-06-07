"""Gemini 3.1 AI provider — full implementation for device analysis and troubleshooting.

Uses google-genai SDK (v1.51.0+) with:
- Gemini 3.1 Flash for fast diagnose analysis (phonectl diagnose --ai)
- Gemini 3.1 Pro for deep troubleshooting (phonectl ask)

Setup:
    pip install google-genai>=1.51.0
    export GEMINI_API_KEY=your-api-key

Privacy: Only non-PII device context is sent (manufacturer, model, codename,
Android version, VNDK, kernel, RAM, scores). Never serial, IMEI, or accounts.
"""

from __future__ import annotations

import os
from dataclasses import asdict

from phonectl.ai.base import AIProvider, DeviceContext

FLASH_MODEL = "gemini-3.1-flash-preview"
PRO_MODEL = "gemini-3.1-pro-preview"

SYSTEM_PROMPT = """You are phonectl AI — an expert Android device management assistant.
You analyze device properties, security findings, and performance data to provide
specific, actionable recommendations. Always reference phonectl commands when
suggesting fixes. Be concise and prioritize by impact.

Available phonectl commands:
- phonectl tune --profile fast/balanced/battery/gaming
- phonectl security --harden
- phonectl storage cleanup / storage bloatware disable
- phonectl flash gsi / flash gsi --version <id>
- phonectl audit / audit --deep
- phonectl reset --factory / --clear-cache
- phonectl recover
- phonectl check / recommend

Focus on:
1. Security risks and how to fix them
2. Performance bottlenecks and optimization
3. Whether the device should be flashed with a newer OS
4. Any anomalies in the data"""


class GeminiProvider(AIProvider):
    """Gemini 3.1 Pro/Flash provider for AI-powered device analysis."""

    def __init__(self, model: str = FLASH_MODEL):
        self.model = model
        self._client = None

    @property
    def name(self) -> str:
        model_short = self.model.replace("-preview", "").replace("gemini-", "Gemini ")
        return f"Gemini ({model_short})"

    def _get_client(self):
        if self._client is None:
            try:
                from google import genai
                api_key = os.environ.get("GEMINI_API_KEY", "")
                if not api_key:
                    raise ValueError("GEMINI_API_KEY environment variable not set")
                self._client = genai.Client(api_key=api_key)
            except ImportError:
                raise ImportError(
                    "google-genai package not installed. "
                    "Run: pip install google-genai>=1.51.0"
                )
        return self._client

    def is_available(self) -> bool:
        """Check if Gemini API key is set and SDK is installed."""
        api_key = os.environ.get("GEMINI_API_KEY", "")
        if not api_key:
            return False
        try:
            from google import genai
            return True
        except ImportError:
            return False

    def analyze(self, context: DeviceContext) -> str:
        """Send device context to Gemini Flash for analysis."""
        client = self._get_client()

        context_text = self._format_context(context)
        prompt = (
            f"Analyze this Android device and provide recommendations:\n\n"
            f"{context_text}\n\n"
            f"Provide:\n"
            f"1. Top 3 issues by priority\n"
            f"2. Specific phonectl commands to fix each\n"
            f"3. Any patterns or anomalies you notice\n"
            f"4. Overall device health assessment (one line)"
        )

        try:
            response = client.models.generate_content(
                model=self.model,
                contents=prompt,
                config={"system_instruction": SYSTEM_PROMPT},
            )
            return response.text
        except Exception as exc:
            return f"Gemini analysis failed: {exc}"

    def troubleshoot(self, context: DeviceContext, question: str) -> str:
        """Answer a troubleshooting question using Gemini Pro."""
        client = self._get_client()

        context_text = self._format_context(context)
        prompt = (
            f"Device context:\n{context_text}\n\n"
            f"User question: {question}\n\n"
            f"Provide a specific, actionable answer. Reference phonectl commands where applicable."
        )

        pro_model = PRO_MODEL
        try:
            response = client.models.generate_content(
                model=pro_model,
                contents=prompt,
                config={"system_instruction": SYSTEM_PROMPT},
            )
            return response.text
        except Exception as exc:
            return f"Gemini troubleshooting failed: {exc}"

    def _format_context(self, context: DeviceContext) -> str:
        """Format device context as readable text for the prompt."""
        lines = []
        data = asdict(context)
        for key, value in data.items():
            if value and value != 0 and value != 0.0 and value != []:
                label = key.replace("_", " ").title()
                if isinstance(value, list):
                    value = ", ".join(str(v) for v in value)
                lines.append(f"  {label}: {value}")
        return "\n".join(lines)
