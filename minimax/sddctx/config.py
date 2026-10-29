# Copyright (c) 2026 OceanBase.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Runtime configuration for the SDD context module."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

#: Default PowerContext Server base URL.
DEFAULT_POWERCONTEXT_URL = "http://127.0.0.1:8000"

#: Default MiniMax Messages API base URL.
DEFAULT_MINIMAX_BASE_URL = "https://agent.minimax.cn/mavis/api/v1/llm/v1"

#: Default MiniMax model used to drive the code modification.
DEFAULT_MINIMAX_MODEL = "MiniMax-M3.1-Flash"


@dataclass(frozen=True)
class Settings:
    """Resolved runtime settings.

    Attributes:
        root: Project root that holds ``specs/`` and the business project.
        db_dir: Directory used by the embedded seekDB instance.
        powercontext_url: Base URL of the PowerContext Server.
        scope_id: PowerContext Scope that holds task state.
        powercontext_token: Optional bearer token for an authenticated Server.
        minimax_base_url: Base URL of the MiniMax Messages API.
        minimax_model: MiniMax model identifier.
        minimax_api_key: MiniMax API key or access token.
        minimax_timeout: Per-request timeout in seconds.
    """

    root: Path
    db_dir: Path
    powercontext_url: str
    scope_id: str
    powercontext_token: str | None
    minimax_base_url: str
    minimax_model: str
    minimax_api_key: str | None
    minimax_timeout: float

    @property
    def specs_dir(self) -> Path:
        """Directory holding the SDD specification documents."""
        return self.root / "specs"

    @property
    def project_dir(self) -> Path:
        """Directory holding the business project under development."""
        return self.root / "demo_shop"

    @property
    def state_file(self) -> Path:
        """Local file that mirrors the last known task state pointer."""
        return self.root / ".sddctx" / "state.json"


def load_settings(root: Path | str | None = None) -> Settings:
    """Build :class:`Settings` from the environment.

    Environment variables:
        SDDCTX_ROOT: Project root. Defaults to the current working directory.
        SDDCTX_DB_DIR: Embedded seekDB directory. Defaults to ``<root>/.sddctx/seekdb``.
        SDDCTX_POWERCONTEXT_URL: PowerContext Server base URL.
        SDDCTX_SCOPE_ID: PowerContext Scope id used for task state.
        SDDCTX_POWERCONTEXT_TOKEN: Bearer token for an authenticated Server.
        MINIMAX_BASE_URL: MiniMax Messages API base URL.
        MINIMAX_MODEL: MiniMax model identifier.
        MINIMAX_API_KEY: MiniMax API key or access token.
        MINIMAX_TIMEOUT: Per-request timeout in seconds.

    Args:
        root: Explicit project root that overrides ``SDDCTX_ROOT``.

    Returns:
        Resolved settings.
    """
    resolved_root = Path(root or os.environ.get("SDDCTX_ROOT") or Path.cwd()).resolve()
    db_dir = Path(os.environ.get("SDDCTX_DB_DIR") or (resolved_root / ".sddctx" / "seekdb")).resolve()
    timeout = float(os.environ.get("MINIMAX_TIMEOUT", "180"))
    return Settings(
        root=resolved_root,
        db_dir=db_dir,
        powercontext_url=os.environ.get("SDDCTX_POWERCONTEXT_URL", DEFAULT_POWERCONTEXT_URL).rstrip("/"),
        scope_id=os.environ.get("SDDCTX_SCOPE_ID", "sdd-context-demo"),
        powercontext_token=os.environ.get("SDDCTX_POWERCONTEXT_TOKEN") or None,
        minimax_base_url=os.environ.get("MINIMAX_BASE_URL", DEFAULT_MINIMAX_BASE_URL).rstrip("/"),
        minimax_model=os.environ.get("MINIMAX_MODEL", DEFAULT_MINIMAX_MODEL),
        minimax_api_key=os.environ.get("MINIMAX_API_KEY") or None,
        minimax_timeout=timeout,
    )
