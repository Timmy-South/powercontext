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

"""Minimal MiniMax Messages API client.

The client speaks the Anthropic compatible ``POST /messages`` protocol that
the MiniMax platform exposes. Only the fields the module needs are sent, and
the response is reduced to plain text plus the usage counters that the
technical record reports.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MiniMaxResponse:
    """Result of one MiniMax request.

    Attributes:
        text: Text returned by the model.
        model: Model that produced the answer.
        input_tokens: Number of input tokens reported by the API.
        output_tokens: Number of output tokens reported by the API.
        raw: The decoded response body.
    """

    text: str
    model: str
    input_tokens: int
    output_tokens: int
    raw: dict[str, Any]


class MiniMaxError(RuntimeError):
    """Raised when the MiniMax API rejects a request."""


class MiniMaxClient:
    """Calls the MiniMax Messages API."""

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str | None,
        timeout: float = 180.0,
    ) -> None:
        """Configure the client.

        Args:
            base_url: Base URL of the Messages API.
            model: Model identifier.
            api_key: API key or access token.
            timeout: Per-request timeout in seconds.
        """
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout = timeout

    def complete(
        self,
        *,
        system: str,
        prompt: str,
        max_tokens: int = 8192,
        temperature: float = 0.0,
    ) -> MiniMaxResponse:
        """Run one completion.

        Args:
            system: System prompt.
            prompt: User prompt.
            max_tokens: Maximum number of output tokens.
            temperature: Sampling temperature.

        Returns:
            The model answer.

        Raises:
            MiniMaxError: When the API responds with an error status.
        """
        payload = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "system": system,
            "messages": [{"role": "user", "content": prompt}],
        }
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        request = urllib.request.Request(
            f"{self.base_url}/messages",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise MiniMaxError(f"MiniMax API returned HTTP {error.code}: {detail[:500]}") from error
        except urllib.error.URLError as error:
            raise MiniMaxError(f"MiniMax API request failed: {error.reason}") from error

        text = "".join(
            block.get("text", "")
            for block in body.get("content", [])
            if isinstance(block, dict) and block.get("type") == "text"
        )
        usage = body.get("usage", {})
        return MiniMaxResponse(
            text=text,
            model=str(body.get("model", self.model)),
            input_tokens=int(usage.get("input_tokens", 0)),
            output_tokens=int(usage.get("output_tokens", 0)),
            raw=body,
        )
