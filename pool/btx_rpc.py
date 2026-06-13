"""JSON-RPC 1.0 client for btxd."""

from __future__ import annotations

import base64
import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


class RpcError(RuntimeError):
    def __init__(self, code: int, message: str):
        super().__init__(f"RPC error {code}: {message}")
        self.code = code
        self.message = message


class BtxRpcClient:
    def __init__(
        self,
        url: str = "http://127.0.0.1:19334",
        rpc_user: str = "",
        rpc_password: str = "",
        cookie_file: str = "",
        wallet: str = "",
        timeout: float = 60.0,
    ):
        base_url = url.rstrip("/")
        if wallet:
            base_url += "/wallet/" + urllib.parse.quote(wallet, safe="")
            self.url = base_url
        else:
            self.url = base_url + "/"
        self.timeout = timeout
        self._msg_id = 0
        self._auth_header = self._build_auth(rpc_user, rpc_password, cookie_file)

    @staticmethod
    def _build_auth(user: str, password: str, cookie_file: str) -> str:
        if user and password:
            token = f"{user}:{password}"
        else:
            candidates: list[Path] = []
            if cookie_file:
                candidates.append(Path(cookie_file).expanduser())
            candidates.append(Path.home() / ".btx" / ".cookie")
            token = ""
            for path in candidates:
                if path.is_file():
                    token = path.read_text().strip()
                    break
            if not token:
                raise RuntimeError(
                    "no RPC credentials: set rpc_user/rpc_password in config.yaml, "
                    "or ensure ~/.btx/.cookie exists (btxd with server=1)"
                )
        return "Basic " + base64.b64encode(token.encode()).decode()

    def call(self, method: str, params: list | None = None, timeout: float | None = None) -> Any:
        self._msg_id += 1
        payload = json.dumps({
            "jsonrpc": "1.0",
            "id": self._msg_id,
            "method": method,
            "params": params or [],
        }).encode()
        req = urllib.request.Request(
            self.url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": self._auth_header,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as resp:
                body = json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")
            raise RuntimeError(f"RPC HTTP {e.code}: {detail}") from e
        except urllib.error.URLError as e:
            raise ConnectionError(f"RPC connection failed: {e}") from e

        if body.get("error"):
            err = body["error"]
            raise RpcError(err.get("code", -1), err.get("message", str(err)))
        return body.get("result")

    def send_to_address(
        self, address: str, amount_btx: float, comment: str = ""
    ) -> str:
        params: list[Any] = [address, amount_btx]
        if comment:
            params.append(comment)
        result = self.call("sendtoaddress", params, timeout=120.0)
        return str(result)

    def get_wallet_balance(self) -> float:
        return float(self.call("getbalance", [], timeout=30.0) or 0)
