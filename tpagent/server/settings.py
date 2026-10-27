"""Server settings: env vars (TPAGENT_TOKEN, TPAGENT_WORKSPACE, PORT) + CLI overrides."""
from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

from tpagent.config import Config, load_config

DEFAULT_PORT = 8080
APPROVAL_TIMEOUT_S = 600  # 10 minutes, then the dangerous call is denied


@dataclass
class Settings:
    token: str
    workspace: Path
    port: int = DEFAULT_PORT
    host: str = "0.0.0.0"
    generated_token: bool = False
    config: Config = field(default_factory=load_config)

    @classmethod
    def from_env(
        cls,
        token: str | None = None,
        workspace: str | Path | None = None,
        port: int | None = None,
        config: Config | None = None,
    ) -> "Settings":
        env_token = token or os.environ.get("TPAGENT_TOKEN") or ""
        generated = not env_token
        ws = Path(workspace or os.environ.get("TPAGENT_WORKSPACE") or "workspace").expanduser().resolve()
        ws.mkdir(parents=True, exist_ok=True)
        return cls(
            token=env_token or secrets.token_urlsafe(24),
            workspace=ws,
            port=int(port or os.environ.get("PORT") or DEFAULT_PORT),
            generated_token=generated,
            config=config if config is not None else load_config(),
        )
