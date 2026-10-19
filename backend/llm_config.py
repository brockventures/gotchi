#!/usr/bin/env python3
"""
GOTCHI V1 — User-Customizable LLM & Audio Sink Configuration (`backend/llm_config.py`)
======================================================================================
Satisfies:
- User-customizable LLM backend supporting both:
  1. `api_key` mode: Metered provider API keys (Gemini Multimodal Live, OpenAI, Anthropic, custom).
  2. `subscription` mode: Personal subscription account hooks (CLI bridge like `claude` / `agy`,
     local subscription proxy URL, or OAuth/session token) without metered API billing.
  3. `mock` mode (default): Zero-cost offline deterministic test provider.
- Configurable Discord voice sink bot target (`discord_voice_bot`: `zero` | `mirrormere` | `custom`)
  and webhook/bridge URL (`discord_voice_webhook_url`) for `T3.3` (`audio_out_mode: "discord_voice"`).
"""

from dataclasses import dataclass
import json
import os
from pathlib import Path
import shlex
from typing import Any, Dict, Mapping, Optional

VALID_AUTH_MODES = ("mock", "api_key", "subscription")
VALID_PROVIDERS = (
    "mock",
    "gemini",
    "openai",
    "anthropic",
    "claude_subscription",
    "gemini_subscription",
    "openai_subscription",
    "custom",
)
VALID_DISCORD_BOTS = ("zero", "mirrormere", "custom")
ALLOWED_SUBSCRIPTION_BINARIES = ("claude", "agy", "gemini", "codex")


@dataclass
class LLMConfig:
    auth_mode: str = "mock"
    provider: str = "mock"
    model: str = "gemini-2.0-flash-live"
    api_key: str = ""
    base_url: str = ""
    subscription_command: str = ""
    subscription_url: str = ""
    session_token: str = ""
    discord_voice_bot: str = "zero"
    discord_voice_webhook_url: str = ""

    def validate(self) -> None:
        if self.auth_mode not in VALID_AUTH_MODES:
            raise ValueError(
                f"Invalid auth_mode '{self.auth_mode}'; expected one of {VALID_AUTH_MODES}"
            )
        if self.provider not in VALID_PROVIDERS:
            raise ValueError(
                f"Invalid provider '{self.provider}'; expected one of {VALID_PROVIDERS}"
            )
        if self.discord_voice_bot not in VALID_DISCORD_BOTS:
            raise ValueError(
                f"Invalid discord_voice_bot '{self.discord_voice_bot}'; expected one of {VALID_DISCORD_BOTS}"
            )
        if self.auth_mode == "api_key" and not self.api_key.strip():
            raise ValueError("auth_mode 'api_key' requires a non-empty api_key")
        if self.auth_mode == "subscription":
            if not (
                self.subscription_command.strip()
                or self.subscription_url.strip()
                or self.session_token.strip()
            ):
                raise ValueError(
                    "auth_mode 'subscription' requires subscription_command, subscription_url, or session_token"
                )
            if self.subscription_command.strip():
                argv = shlex.split(self.subscription_command.strip())
                if not argv:
                    raise ValueError("subscription_command cannot be empty when specified")
                binary_name = Path(argv[0]).name
                if binary_name not in ALLOWED_SUBSCRIPTION_BINARIES:
                    raise ValueError(
                        f"Unsupported subscription_command binary '{binary_name}'; "
                        f"expected one of {ALLOWED_SUBSCRIPTION_BINARIES}"
                    )

    def to_public_dict(self) -> Dict[str, Any]:
        """Returns safe, redacted dictionary representation (never leaks raw keys/tokens)."""
        return {
            "auth_mode": self.auth_mode,
            "provider": self.provider,
            "model": self.model,
            "api_key_set": bool(self.api_key.strip()),
            "base_url": self.base_url,
            "subscription_command": self.subscription_command,
            "subscription_url": self.subscription_url,
            "session_token_set": bool(self.session_token.strip()),
            "discord_voice_bot": self.discord_voice_bot,
            "discord_voice_webhook_url": self.discord_voice_webhook_url,
        }

    def update_from_dict(self, updates: Mapping[str, Any]) -> "LLMConfig":
        """Applies partial user updates, validates before committing, and returns self."""
        candidate = LLMConfig(
            auth_mode=str(updates.get("auth_mode", self.auth_mode)),
            provider=str(updates.get("provider", self.provider)),
            model=str(updates.get("model", self.model)),
            api_key=str(updates.get("api_key", self.api_key)),
            base_url=str(updates.get("base_url", self.base_url)),
            subscription_command=str(updates.get("subscription_command", self.subscription_command)),
            subscription_url=str(updates.get("subscription_url", self.subscription_url)),
            session_token=str(updates.get("session_token", self.session_token)),
            discord_voice_bot=str(updates.get("discord_voice_bot", self.discord_voice_bot)),
            discord_voice_webhook_url=str(
                updates.get("discord_voice_webhook_url", self.discord_voice_webhook_url)
            ),
        )
        candidate.validate()
        self.auth_mode = candidate.auth_mode
        self.provider = candidate.provider
        self.model = candidate.model
        self.api_key = candidate.api_key
        self.base_url = candidate.base_url
        self.subscription_command = candidate.subscription_command
        self.subscription_url = candidate.subscription_url
        self.session_token = candidate.session_token
        self.discord_voice_bot = candidate.discord_voice_bot
        self.discord_voice_webhook_url = candidate.discord_voice_webhook_url
        return self

    @classmethod
    def from_env_or_file(cls, config_path: Optional[str] = None) -> "LLMConfig":
        path_str = config_path or os.environ.get("GOTCHI_LLM_CONFIG_FILE", "")
        file_data: Dict[str, Any] = {}
        if path_str:
            p = Path(path_str)
            if p.is_file():
                file_data = json.loads(p.read_text(encoding="utf-8"))

        auth_mode = os.environ.get("GOTCHI_LLM_AUTH_MODE", file_data.get("auth_mode", "mock"))
        provider = os.environ.get("GOTCHI_LLM_PROVIDER", file_data.get("provider", "mock"))
        model = os.environ.get(
            "GOTCHI_LLM_MODEL", file_data.get("model", "gemini-2.0-flash-live")
        )
        api_key = os.environ.get(
            "GOTCHI_LLM_API_KEY",
            file_data.get("api_key", os.environ.get("GEMINI_API_KEY", "")),
        )
        base_url = os.environ.get("GOTCHI_LLM_BASE_URL", file_data.get("base_url", ""))
        subscription_command = os.environ.get(
            "GOTCHI_LLM_SUBSCRIPTION_CMD", file_data.get("subscription_command", "")
        )
        subscription_url = os.environ.get(
            "GOTCHI_LLM_SUBSCRIPTION_URL", file_data.get("subscription_url", "")
        )
        session_token = os.environ.get(
            "GOTCHI_LLM_SESSION_TOKEN", file_data.get("session_token", "")
        )
        discord_voice_bot = os.environ.get(
            "GOTCHI_DISCORD_VOICE_BOT", file_data.get("discord_voice_bot", "zero")
        )
        discord_voice_webhook_url = os.environ.get(
            "GOTCHI_DISCORD_VOICE_URL", file_data.get("discord_voice_webhook_url", "")
        )

        cfg = cls(
            auth_mode=auth_mode,
            provider=provider,
            model=model,
            api_key=api_key,
            base_url=base_url,
            subscription_command=subscription_command,
            subscription_url=subscription_url,
            session_token=session_token,
            discord_voice_bot=discord_voice_bot,
            discord_voice_webhook_url=discord_voice_webhook_url,
        )
        cfg.validate()
        return cfg
