"""Per-miner Stratum session handler."""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
import time
from collections import OrderedDict
from typing import Any, Callable

from pool import PROTOCOL_CAPABILITIES, USER_AGENT

log = logging.getLogger(__name__)

STALE_JOB_CODES = (21, 23)


def parse_stratum_user(username: str, fallback_worker: str = "worker") -> tuple[str, str]:
    """Split ``address.worker`` usernames used by btx-nvidia-miner."""
    username = username.strip()
    if not username:
        return "", fallback_worker or "worker"
    dot = username.rfind(".")
    if dot <= 0 or dot >= len(username) - 1:
        return username, fallback_worker or "worker"
    address = username[:dot]
    worker = username[dot + 1 :]
    if not address.startswith("btx1"):
        return username, fallback_worker or "worker"
    return address, worker or fallback_worker or "worker"


class StratumSession:
    def __init__(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        *,
        on_submit: Callable[..., Any],
        on_authorize: Callable[..., Any],
        on_metrics: Callable[..., Any] | None = None,
        get_job_notify: Callable[[float | None], list | None],
        get_difficulty: Callable[[], float],
        vardiff_callback: Callable[[str, float], float] | None = None,
        send_canonical_name: bool = True,
        max_pending_submits: int = 8,
        max_message_bytes: int = 16384,
    ):
        self.reader = reader
        self.writer = writer
        self.on_submit = on_submit
        self.on_authorize = on_authorize
        self.on_metrics = on_metrics
        self.get_job_notify = get_job_notify
        self.get_difficulty = get_difficulty
        self.vardiff_callback = vardiff_callback
        self.peer = writer.get_extra_info("peername")
        self._msg_id = 0
        self._extranonce1 = secrets.token_hex(4)
        self._extranonce2_size = 4
        self._subscribed = False
        self._authorized = False
        self._address = ""
        self._worker_name = ""
        self._canonical_name = ""
        self._operator_label = ""
        self._session_difficulty = 0.01
        self._authorized_at = 0.0
        self._last_share_at = 0.0
        self._shares_session = 0
        self._closed = False
        self._send_lock = asyncio.Lock()
        self._max_pending_submits = max(1, int(max_pending_submits))
        self._max_message_bytes = max(1024, int(max_message_bytes))
        self._submit_tasks: set[asyncio.Task] = set()
        self._job_assignments: OrderedDict[str, tuple[str, float]] = OrderedDict()
        self._job_assignment_seq = 0
        self._vardiff_lock = asyncio.Lock()
        self._send_canonical_name = send_canonical_name

    async def send(self, msg: dict) -> None:
        if self._closed:
            return
        data = json.dumps(msg, separators=(",", ":")) + "\n"
        async with self._send_lock:
            self.writer.write(data.encode())
            await self.writer.drain()

    async def send_notify(self, params: list) -> None:
        assigned = list(params)
        source_job_id = str(assigned[0])
        self._job_assignment_seq += 1
        assigned_job_id = (
            f"{source_job_id}.{self._extranonce1}.{self._job_assignment_seq:x}"
        )
        assigned[0] = assigned_job_id
        self._job_assignments[assigned_job_id] = (
            source_job_id,
            self._session_difficulty,
        )
        while len(self._job_assignments) > 64:
            self._job_assignments.popitem(last=False)
        await self.send({
            "id": None,
            "method": "mining.notify",
            "params": assigned,
        })

    async def send_set_difficulty(self, difficulty: float) -> None:
        self._session_difficulty = difficulty
        await self.send({"id": None, "method": "mining.set_difficulty", "params": [difficulty]})

    async def send_canonical_name(self, name: str) -> None:
        await self.send({
            "id": None,
            "method": "mining.set_canonical_name",
            "params": [{"canonical_name": name}],
        })

    async def handle(self) -> None:
        try:
            while not self._closed:
                line = await self.reader.readline()
                if not line:
                    break
                if len(line) > self._max_message_bytes:
                    log.warning("oversized stratum message from %s", self.peer)
                    break
                try:
                    msg = json.loads(line.decode().strip())
                except json.JSONDecodeError:
                    continue
                await self._dispatch(msg)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            log.warning("session error %s: %s", self.peer, e)
        finally:
            await self.close()

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self.writer.close()
            await self.writer.wait_closed()
        except Exception:
            pass

    async def _dispatch(self, msg: dict) -> None:
        req_id = msg.get("id")
        method = msg.get("method")
        params = msg.get("params") or []

        if method == "mining.subscribe":
            await self._handle_subscribe(req_id, params)
        elif method == "mining.authorize":
            await self._handle_authorize(req_id, params)
        elif method == "mining.submit":
            if len(self._submit_tasks) >= self._max_pending_submits:
                await self.send({
                    "id": req_id,
                    "result": False,
                    "error": [20, "Too many pending shares; retry shortly", None],
                })
                return
            submitted_job_id = str(params[1]) if len(params) > 1 else ""
            source_job_id, submit_difficulty = self._job_assignments.get(
                submitted_job_id,
                (submitted_job_id, self._session_difficulty),
            )
            task = asyncio.create_task(
                self._run_submit(
                    req_id,
                    params,
                    source_job_id,
                    submit_difficulty,
                )
            )
            self._submit_tasks.add(task)
            task.add_done_callback(self._submit_tasks.discard)
        elif method == "mining.extranonce.subscribe":
            await self.send({"id": req_id, "result": True, "error": None})
        elif method == "worker.report_metrics":
            await self._handle_report_metrics(params)
        elif method == "mining.configure":
            return
        else:
            if req_id is not None:
                await self.send({
                    "id": req_id,
                    "result": None,
                    "error": [20, f"Unknown method: {method}", None],
                })

    async def _run_submit(
        self,
        req_id: Any,
        params: list,
        source_job_id: str,
        submit_difficulty: float,
    ) -> None:
        try:
            await self._handle_submit(
                req_id,
                params,
                source_job_id,
                submit_difficulty,
            )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning("submit error %s req_id=%s: %s", self.peer, req_id, e)
            await self.send({
                "id": req_id,
                "result": False,
                "error": [20, "Internal share validation error", None],
            })

    async def _handle_subscribe(self, req_id: Any, params: list) -> None:
        user_agent = params[0] if params else USER_AGENT
        extension = params[1] if len(params) > 1 and isinstance(params[1], dict) else {}
        self._operator_label = str(extension.get("operator_label", "") or "")
        sub_id = secrets.token_hex(4)
        await self.send({
            "id": req_id,
            "result": [
                [["mining.set_difficulty", sub_id], ["mining.notify", sub_id]],
                self._extranonce1,
                self._extranonce2_size,
            ],
            "error": None,
        })
        self._subscribed = True
        log.info(
            "subscribe %s agent=%s caps=%s",
            self.peer, user_agent, extension.get("protocol_compliant", PROTOCOL_CAPABILITIES),
        )

    async def _push_work(self) -> None:
        try:
            await self.send_set_difficulty(self.get_difficulty())
            notify = self.get_job_notify(self._session_difficulty)
            if notify:
                await self.send_notify(notify)
                log.info("pushed job %s to %s", notify[0], self.peer)
            else:
                log.warning(
                    "no active job for %s — miner will idle until btxd syncs or template fetch succeeds",
                    self.peer,
                )
        except Exception as e:
            log.warning("push work failed for %s: %s", self.peer, e)

    async def _handle_authorize(self, req_id: Any, params: list) -> None:
        raw_user = str(params[0]) if params else ""
        address, worker = parse_stratum_user(raw_user, self._operator_label or "worker")
        if not address.startswith("btx1"):
            await self.send({"id": req_id, "result": False, "error": [24, "Invalid address", None]})
            return

        self._address = address
        self._worker_name = worker
        self._canonical_name = f"{address}.{worker}"

        try:
            ok = await asyncio.wait_for(
                self.on_authorize(address, worker), timeout=15.0
            )
        except Exception as e:
            log.warning("miner registration error for %s: %s", address[:16], e)
            ok = False
        if not ok:
            await self.send({
                "id": req_id,
                "result": False,
                "error": [24, "Invalid BTX address", None],
            })
            return

        await self.send({"id": req_id, "result": True, "error": None})
        self._authorized = True
        self._authorized_at = time.time()
        log.info("authorized %s as %s (req_id=%s)", self.peer, self._canonical_name, req_id)
        asyncio.create_task(self._push_work())
        if self._send_canonical_name:
            try:
                await self.send_canonical_name(self._canonical_name)
            except Exception as e:
                log.warning("canonical name push failed for %s: %s", self.peer, e)

    async def _handle_report_metrics(self, params: list) -> None:
        if not self._authorized or not self.on_metrics:
            return
        if not params:
            return
        payload = params[0]
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                return
        if not isinstance(payload, dict):
            return
        solver_sha = str(payload.get("solver_sha256") or "")
        if solver_sha:
            log.info(
                "worker metrics %s solver=%s backend=%s wrapper=%s",
                self._canonical_name,
                solver_sha[:12],
                payload.get("solver_backend", ""),
                payload.get("wrapper_version", ""),
            )
        try:
            solver_nps = float(payload.get("solver_nps") or 0)
        except (TypeError, ValueError):
            return
        if solver_nps <= 0:
            return
        try:
            await self.on_metrics(self._canonical_name, solver_nps)
        except Exception as e:
            log.debug("metrics callback failed for %s: %s", self.peer, e)

    async def _handle_submit(
        self,
        req_id: Any,
        params: list,
        source_job_id: str,
        submit_difficulty: float,
    ) -> None:
        if not self._authorized:
            await self.send({"id": req_id, "result": False, "error": [25, "Not authorized", None]})
            return
        if len(params) < 5:
            await self.send({"id": req_id, "result": False, "error": [20, "Malformed submit", None]})
            return

        worker, _job_id, extranonce2, ntime_hex, nonce_hex = params[:5]
        try:
            ntime = int(ntime_hex, 16)
            nonce64 = int(nonce_hex, 16)
        except ValueError:
            await self.send({"id": req_id, "result": False, "error": [20, "Invalid nonce/ntime", None]})
            return

        result = await self.on_submit(
            address=self._address,
            worker_name=self._worker_name,
            canonical_name=self._canonical_name,
            job_id=source_job_id,
            extranonce2=str(extranonce2),
            ntime=ntime,
            nonce64=nonce64,
            difficulty=submit_difficulty,
        )

        if result.get("accepted"):
            await self.send({"id": req_id, "result": True, "error": None})
            self._shares_session += 1
            self._last_share_at = time.time()
            if self.vardiff_callback:
                async with self._vardiff_lock:
                    # An accepted share from an older assignment must not
                    # readjust the current target or create a notify storm.
                    if abs(submit_difficulty - self._session_difficulty) <= 1e-9:
                        new_diff = self.vardiff_callback(
                            self._canonical_name,
                            self._session_difficulty,
                        )
                        if abs(new_diff - self._session_difficulty) > 1e-9:
                            await self.send_set_difficulty(new_diff)
                            notify = self.get_job_notify(new_diff)
                            if notify:
                                await self.send_notify(notify)
        else:
            code = int(result.get("error_code", 23))
            reason = str(result.get("error", "rejected"))
            await self.send({"id": req_id, "result": False, "error": [code, reason, None]})
