#!/usr/bin/env python3
"""
GOTCHI V1 — User-Customizable LLM & Audio Sink Configuration (`backend/llm_config.py`)
======================================================================================
Satisfies:
- User-customizable LLM backend supporting both:
  1. `api_key` mode: Metered provider API keys (Gemini Multimodal Live, OpenAI, Anthropic, custom).
  2. `subscription` mode: Personal subscription account hooks (gateway-configured CLI bridge like
     `claude` / `agy`, local subscription proxy URL, or OAuth/session token) without metered API billing.
  3. `mock` mode (default): Zero-cost offline deterministic test provider.
- Security invariants:
  - `subscription_command` can ONLY be loaded from gateway environment (`GOTCHI_LLM_SUBSCRIPTION_CMD`)
    or gateway config file (`GOTCHI_LLM_CONFIG_FILE`), NEVER modified via HTTP request body.
  - `subscription_command` binary must be a bare binary name in `ALLOWED_SUBSCRIPTION_BINARIES`
    (no path traversal like `/tmp/x/claude`) and rejects dangerous execution flags.
  - `discord_voice_webhook_url` is validated against `https://` and `ALLOWED_DISCORD_WEBHOOK_HOSTS`
    to prevent SSRF against internal addresses.
- Mirrormere Section 5c voice tuning parameters (`reply_cap_words`, `filler_delay_ms`,
  `second_filler_delay_ms`, `min_voiced_ms`).
"""

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import shlex
from typing import Any, Dict, Mapping, Optional, Tuple
from urllib.parse import urlparse

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
VALID_TTS_ENGINES = ("mock", "gemini", "kokoro", "custom")
VALID_STT_ENGINES = ("mock", "whisper_http", "faster_whisper")
DEFAULT_VOICE_NAME = "Schedar"
GEMINI_HD_VOICES = (
    "Schedar",
    "Achird",
    "Puck",
    "Charon",
    "Kore",
    "Fenrir",
    "Aoede",
    "Orus",
    "Zephyr",
    "Autonoe",
    "Enceladus",
    "Iapetus",
    "Umbriel",
    "Algieba",
    "Despina",
    "Erinome",
    "Algenib",
    "Rasalgethi",
    "Laomedeia",
    "Achernar",
    "Alnilam",
    "Gacrux",
    "Pulcherrima",
    "Vindemiatrix",
    "Sadachbia",
    "Sadaltager",
    "Sulafat",
    "Callirrhoe",
    "Leda",
    "Zubenelgenubi",
)
KOKORO_VOICES = (
    "am_schedar",
    "am_michael",
    "am_adam",
    "am_fenrir",
    "am_onyx",
    "bm_george",
    "bm_lewis",
    "af_heart",
    "af_bella",
)
ALLOWED_SUBSCRIPTION_BINARIES = ("claude", "agy", "gemini", "codex")
FORBIDDEN_SUBSCRIPTION_ARGS = (
    "--dangerously-skip-permissions",
    "exec",
    "-c",
    "--eval",
    "-e",
)
ALLOWED_DISCORD_WEBHOOK_HOSTS: Tuple[str, ...] = (
    "discord.com",
    "discordapp.com",
    "canary.discord.com",
    "ptb.discord.com",
)


def validate_discord_webhook_url(
    url: str,
    allowed_hosts: Optional[Tuple[str, ...]] = None,
) -> None:
    """
    Validates that a Discord webhook URL uses `https://` and targets an allowlisted host.
    Raises ValueError on any scheme, host, or credential violation.
    """
    cleaned = url.strip()
    if not cleaned:
        return

    env_hosts = os.environ.get("GOTCHI_ALLOWED_WEBHOOK_HOSTS", "").strip()
    if allowed_hosts is not None:
        hosts = allowed_hosts
    elif env_hosts:
        hosts = tuple(h.strip().lower() for h in env_hosts.split(",") if h.strip())
    else:
        hosts = ALLOWED_DISCORD_WEBHOOK_HOSTS

    parsed = urlparse(cleaned)
    if parsed.scheme != "https":
        raise ValueError(
            f"Invalid discord_voice_webhook_url scheme '{parsed.scheme}'; only 'https' is allowed"
        )
    if parsed.username or parsed.password:
        raise ValueError("discord_voice_webhook_url must not contain embedded credentials")
    hostname = (parsed.hostname or "").lower()
    if not hostname or hostname not in hosts:
        raise ValueError(
            f"Disallowed discord_voice_webhook_url host '{hostname}'; expected one of {hosts}"
        )


def validate_subscription_command(cmd: str) -> None:
    """
    Validates a gateway-configured subscription CLI command.
    Requires a bare binary name (no slash/path traversal) in ALLOWED_SUBSCRIPTION_BINARIES
    and blocks dangerous flags/subcommands.
    """
    cleaned = cmd.strip()
    if not cleaned:
        return
    argv = shlex.split(cleaned)
    if not argv:
        raise ValueError("subscription_command cannot be empty when specified")
    binary = argv[0]
    if "/" in binary or "\\" in binary or Path(binary).name != binary:
        raise ValueError(
            f"subscription_command binary '{binary}' must be a bare binary name without path separators"
        )
    if binary not in ALLOWED_SUBSCRIPTION_BINARIES:
        raise ValueError(
            f"Unsupported subscription_command binary '{binary}'; "
            f"expected one of {ALLOWED_SUBSCRIPTION_BINARIES}"
        )
    for arg in argv[1:]:
        if arg in FORBIDDEN_SUBSCRIPTION_ARGS or arg.startswith("--dangerously-"):
            raise ValueError(f"Forbidden argument '{arg}' in subscription_command")


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
    turn_log_webhook_url: str = ""
    node_turn_log_webhooks: Dict[str, str] = field(default_factory=dict)
    voice_name: str = DEFAULT_VOICE_NAME
    tts_engine: str = "kokoro"
    tts_model: str = "gemini-3.8-flash-tts"
    tts_url: str = ""
    stt_engine: str = "mock"
    stt_url: str = ""
    stt_model: str = "whisper-1"
    reply_cap_words: int = 0
    filler_delay_ms: int = 1200
    second_filler_delay_ms: int = 5000
    async_handoff_ms: int = 0
    min_voiced_ms: int = 400
    use_silero_vad: bool = True
    silero_vad_threshold: float = 0.5
    silero_onnx_path: str = ""

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
        if self.tts_engine not in VALID_TTS_ENGINES:
            raise ValueError(
                f"Invalid tts_engine '{self.tts_engine}'; expected one of {VALID_TTS_ENGINES}"
            )
        if self.stt_engine not in VALID_STT_ENGINES:
            raise ValueError(
                f"Invalid stt_engine '{self.stt_engine}'; expected one of {VALID_STT_ENGINES}"
            )
        if not self.voice_name or not str(self.voice_name).strip():
            raise ValueError("voice_name must be a non-empty string")
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
            validate_subscription_command(self.subscription_command)
        if self.discord_voice_webhook_url.strip():
            validate_discord_webhook_url(self.discord_voice_webhook_url)
        if self.turn_log_webhook_url.strip():
            validate_discord_webhook_url(self.turn_log_webhook_url)
        if not isinstance(self.node_turn_log_webhooks, dict):
            raise ValueError("node_turn_log_webhooks must be a dict mapping node_id to webhook URL")
        for n_id, wh_url in self.node_turn_log_webhooks.items():
            if not str(n_id).strip():
                raise ValueError("node_turn_log_webhooks keys must be non-empty node_id strings")
            if str(wh_url).strip():
                validate_discord_webhook_url(str(wh_url))
        if self.reply_cap_words < 0:
            raise ValueError("reply_cap_words must be non-negative (0 disables word cap)")
        if self.filler_delay_ms < 0 or self.second_filler_delay_ms < 0:
            raise ValueError("filler_delay_ms values must be non-negative")
        if self.async_handoff_ms < 0:
            raise ValueError("async_handoff_ms must be non-negative (0 disables async handoff)")
        if self.min_voiced_ms < 0:
            raise ValueError("min_voiced_ms must be non-negative")
        if not (0.0 <= float(self.silero_vad_threshold) <= 1.0):
            raise ValueError("silero_vad_threshold must be between 0.0 and 1.0")

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
            "turn_log_webhook_url": self.turn_log_webhook_url,
            "node_turn_log_webhooks": dict(self.node_turn_log_webhooks),
            "voice_name": self.voice_name,
            "tts_engine": self.tts_engine,
            "tts_model": self.tts_model,
            "tts_url": self.tts_url,
            "stt_engine": self.stt_engine,
            "stt_url": self.stt_url,
            "stt_model": self.stt_model,
            "reply_cap_words": self.reply_cap_words,
            "filler_delay_ms": self.filler_delay_ms,
            "second_filler_delay_ms": self.second_filler_delay_ms,
            "async_handoff_ms": self.async_handoff_ms,
            "min_voiced_ms": self.min_voiced_ms,
            "use_silero_vad": bool(self.use_silero_vad),
            "silero_vad_threshold": float(self.silero_vad_threshold),
        }

    def update_from_dict(self, updates: Mapping[str, Any]) -> "LLMConfig":
        """
        Applies partial runtime updates from the admin HTTP API.
        Rejects any attempt to set `subscription_command` or `silero_onnx_path` over HTTP.
        """
        if "subscription_command" in updates:
            raise ValueError(
                "subscription_command cannot be set via HTTP API; "
                "configure GOTCHI_LLM_SUBSCRIPTION_CMD in gateway environment or config file"
            )
        if "silero_onnx_path" in updates:
            raise ValueError(
                "silero_onnx_path cannot be set via HTTP API; "
                "configure GOTCHI_SILERO_ONNX_PATH in gateway environment or config file"
            )

        raw_node_map = updates.get("node_turn_log_webhooks", self.node_turn_log_webhooks)
        if not isinstance(raw_node_map, Mapping):
            raise ValueError("node_turn_log_webhooks must be an object mapping node_id to webhook URL")
        clean_node_map = {str(k).strip(): str(v).strip() for k, v in raw_node_map.items()}

        candidate = LLMConfig(
            auth_mode=str(updates.get("auth_mode", self.auth_mode)),
            provider=str(updates.get("provider", self.provider)),
            model=str(updates.get("model", self.model)),
            api_key=str(updates.get("api_key", self.api_key)),
            base_url=str(updates.get("base_url", self.base_url)),
            subscription_command=self.subscription_command,
            subscription_url=str(updates.get("subscription_url", self.subscription_url)),
            session_token=str(updates.get("session_token", self.session_token)),
            discord_voice_bot=str(updates.get("discord_voice_bot", self.discord_voice_bot)),
            discord_voice_webhook_url=str(
                updates.get("discord_voice_webhook_url", self.discord_voice_webhook_url)
            ),
            turn_log_webhook_url=str(
                updates.get("turn_log_webhook_url", self.turn_log_webhook_url)
            ),
            node_turn_log_webhooks=clean_node_map,
            voice_name=str(updates.get("voice_name", self.voice_name)).strip(),
            tts_engine=str(updates.get("tts_engine", self.tts_engine)).strip(),
            tts_model=str(updates.get("tts_model", self.tts_model)).strip(),
            tts_url=str(updates.get("tts_url", self.tts_url)).strip(),
            stt_engine=str(updates.get("stt_engine", self.stt_engine)).strip(),
            stt_url=str(updates.get("stt_url", self.stt_url)).strip(),
            stt_model=str(updates.get("stt_model", self.stt_model)).strip(),
            reply_cap_words=int(updates.get("reply_cap_words", self.reply_cap_words)),
            filler_delay_ms=int(updates.get("filler_delay_ms", self.filler_delay_ms)),
            second_filler_delay_ms=int(
                updates.get("second_filler_delay_ms", self.second_filler_delay_ms)
            ),
            async_handoff_ms=int(updates.get("async_handoff_ms", self.async_handoff_ms)),
            min_voiced_ms=int(updates.get("min_voiced_ms", self.min_voiced_ms)),
            use_silero_vad=bool(updates.get("use_silero_vad", self.use_silero_vad)),
            silero_vad_threshold=float(
                updates.get("silero_vad_threshold", self.silero_vad_threshold)
            ),
            silero_onnx_path=self.silero_onnx_path,
        )
        candidate.validate()
        self.auth_mode = candidate.auth_mode
        self.provider = candidate.provider
        self.model = candidate.model
        self.api_key = candidate.api_key
        self.base_url = candidate.base_url
        self.subscription_url = candidate.subscription_url
        self.session_token = candidate.session_token
        self.discord_voice_bot = candidate.discord_voice_bot
        self.discord_voice_webhook_url = candidate.discord_voice_webhook_url
        self.turn_log_webhook_url = candidate.turn_log_webhook_url
        self.node_turn_log_webhooks = candidate.node_turn_log_webhooks
        self.voice_name = candidate.voice_name
        self.tts_engine = candidate.tts_engine
        self.tts_model = candidate.tts_model
        self.tts_url = candidate.tts_url
        self.stt_engine = candidate.stt_engine
        self.stt_url = candidate.stt_url
        self.stt_model = candidate.stt_model
        self.reply_cap_words = candidate.reply_cap_words
        self.filler_delay_ms = candidate.filler_delay_ms
        self.second_filler_delay_ms = candidate.second_filler_delay_ms
        self.async_handoff_ms = candidate.async_handoff_ms
        self.min_voiced_ms = candidate.min_voiced_ms
        self.use_silero_vad = candidate.use_silero_vad
        self.silero_vad_threshold = candidate.silero_vad_threshold
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
        turn_log_webhook_url = os.environ.get(
            "GOTCHI_TURN_LOG_WEBHOOK_URL", file_data.get("turn_log_webhook_url", "")
        )
        raw_node_webhooks = os.environ.get("GOTCHI_NODE_TURN_LOG_WEBHOOKS", "")
        if raw_node_webhooks.strip():
            node_turn_log_webhooks = json.loads(raw_node_webhooks)
        else:
            node_turn_log_webhooks = dict(file_data.get("node_turn_log_webhooks") or {})
        voice_name = os.environ.get(
            "GOTCHI_VOICE_NAME", file_data.get("voice_name", DEFAULT_VOICE_NAME)
        )
        tts_engine = os.environ.get(
            "GOTCHI_TTS_ENGINE", file_data.get("tts_engine", "kokoro")
        )
        tts_model = os.environ.get(
            "GOTCHI_TTS_MODEL", file_data.get("tts_model", "gemini-3.8-flash-tts")
        )
        tts_url = os.environ.get("GOTCHI_TTS_URL", file_data.get("tts_url", ""))
        stt_engine = os.environ.get(
            "GOTCHI_STT_ENGINE", file_data.get("stt_engine", "mock")
        )
        stt_url = os.environ.get("GOTCHI_STT_URL", file_data.get("stt_url", ""))
        stt_model = os.environ.get(
            "GOTCHI_STT_MODEL", file_data.get("stt_model", "whisper-1")
        )
        reply_cap_words = int(
            os.environ.get("GOTCHI_REPLY_CAP_WORDS", file_data.get("reply_cap_words", 0))
        )
        filler_delay_ms = int(
            os.environ.get("GOTCHI_FILLER_DELAY_MS", file_data.get("filler_delay_ms", 1200))
        )
        second_filler_delay_ms = int(
            os.environ.get(
                "GOTCHI_SECOND_FILLER_DELAY_MS", file_data.get("second_filler_delay_ms", 5000)
            )
        )
        async_handoff_ms = int(
            os.environ.get("GOTCHI_ASYNC_HANDOFF_MS", file_data.get("async_handoff_ms", 0))
        )
        min_voiced_ms = int(
            os.environ.get("GOTCHI_MIN_VOICED_MS", file_data.get("min_voiced_ms", 400))
        )
        raw_use_silero = os.environ.get("GOTCHI_USE_SILERO_VAD", "")
        if raw_use_silero.strip():
            use_silero_vad = raw_use_silero.strip().lower() not in ("0", "false", "no")
        else:
            use_silero_vad = bool(file_data.get("use_silero_vad", True))
        silero_vad_threshold = float(
            os.environ.get(
                "GOTCHI_SILERO_VAD_THRESHOLD", file_data.get("silero_vad_threshold", 0.5)
            )
        )
        silero_onnx_path = os.environ.get(
            "GOTCHI_SILERO_ONNX_PATH", file_data.get("silero_onnx_path", "")
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
            turn_log_webhook_url=turn_log_webhook_url,
            node_turn_log_webhooks=node_turn_log_webhooks,
            voice_name=voice_name,
            tts_engine=tts_engine,
            tts_model=tts_model,
            tts_url=tts_url,
            stt_engine=stt_engine,
            stt_url=stt_url,
            stt_model=stt_model,
            reply_cap_words=reply_cap_words,
            filler_delay_ms=filler_delay_ms,
            second_filler_delay_ms=second_filler_delay_ms,
            async_handoff_ms=async_handoff_ms,
            min_voiced_ms=min_voiced_ms,
            use_silero_vad=use_silero_vad,
            silero_vad_threshold=silero_vad_threshold,
            silero_onnx_path=silero_onnx_path,
        )
        cfg.validate()
        return cfg
