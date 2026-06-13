"""BTX mining pool entry point."""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys
import threading

import uvicorn

from pool.api import create_app
from pool.btx_rpc import BtxRpcClient
from pool.config import load_config
from pool.database import PoolDatabase
from pool.job_manager import JobManager
from pool.network_monitor import NetworkMonitor
from pool.payouts import PayoutWorker
from pool.pplns import PplnsEngine
from pool.share_validator import ShareValidator
from pool.stratum.server import StratumServer


def setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


async def run_pool(cfg: dict) -> None:
    rpc = BtxRpcClient(
        url=cfg.get("rpc_url", "http://127.0.0.1:19334"),
        rpc_user=cfg.get("rpc_user", ""),
        rpc_password=cfg.get("rpc_password", ""),
        cookie_file=cfg.get("rpc_cookie_file", ""),
    )
    wallet_rpc = BtxRpcClient(
        url=cfg.get("rpc_url", "http://127.0.0.1:19334"),
        rpc_user=cfg.get("rpc_user", ""),
        rpc_password=cfg.get("rpc_password", ""),
        cookie_file=cfg.get("rpc_cookie_file", ""),
        wallet=cfg.get("rpc_wallet", ""),
    )
    db = PoolDatabase(
        cfg.get("database_path", "data/pool.db"),
        wal=bool(cfg.get("database_wal", True)),
    )
    jobs = JobManager(cfg, rpc)
    network = NetworkMonitor(
        rpc, interval=float(cfg.get("network_stats_interval", 30.0))
    )
    network.start()
    validator = ShareValidator(
        solver_path=cfg.get("solver_path", ""),
        backend=cfg.get("solver_backend", "cpu"),
        runtime_ld_path=cfg.get("solver_runtime_ld_path", ""),
        batch_size=cfg.get("solver_batch_size", 1),
        workers=cfg.get("solver_workers", 4),
    )
    if not validator.available:
        logging.getLogger(__name__).warning(
            "solver_path not set — share validation disabled until you install "
            "btx-gbt-solve (build from https://github.com/thekillsquad007/amdbtx)"
        )

    pplns = PplnsEngine(db, cfg, rpc)
    payouts = PayoutWorker(db, wallet_rpc, cfg)

    def network_difficulty() -> float:
        snap = network.snapshot()
        return float(snap.get("difficulty") or 0)

    stratum = StratumServer(
        cfg,
        jobs,
        db,
        validator,
        rpc,
        pplns=pplns,
        network_difficulty=network_difficulty,
    )
    jobs.start()
    payouts.start()

    maturity_stop = threading.Event()

    def maturity_loop():
        while not maturity_stop.is_set():
            try:
                pplns.poll_maturity()
            except Exception as e:
                logging.getLogger(__name__).warning("maturity poll: %s", e)
            maturity_stop.wait(60.0)

    threading.Thread(target=maturity_loop, daemon=True, name="pplns-maturity").start()

    loop = asyncio.get_running_loop()
    job_event = threading.Event()

    def on_new_job(job):
        if job:
            asyncio.run_coroutine_threadsafe(stratum.broadcast_job(job), loop)

    def poll_jobs():
        last_block_key = None
        while not job_event.is_set():
            block_key = jobs.block_key()
            if jobs.consume_broadcast_flag():
                job = jobs.take_broadcast_job() or jobs.current_job
                if job:
                    if block_key != last_block_key:
                        last_block_key = block_key
                    on_new_job(job)
            job_event.wait(2.0)

    threading.Thread(target=poll_jobs, daemon=True, name="job-broadcast").start()

    await stratum.start()

    def session_count():
        return len(stratum._sessions)

    app = create_app(
        cfg,
        db,
        jobs,
        session_count,
        network,
        payouts,
        stratum_status=stratum.status,
    )
    config = uvicorn.Config(
        app,
        host=cfg.get("api_host", "0.0.0.0"),
        port=int(cfg.get("api_port", 8080)),
        log_level=cfg.get("log_level", "info").lower(),
    )
    server = uvicorn.Server(config)

    async def serve_api():
        await server.serve()

    api_task = asyncio.create_task(serve_api())

    stop = asyncio.Event()

    def _stop(*_):
        stop.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _stop)
        except NotImplementedError:
            pass

    log = logging.getLogger(__name__)
    log.info(
        "BTX pool running — stratum :%s  api :%s  pool %s",
        cfg.get("stratum_port", 3333),
        cfg.get("api_port", 8080),
        cfg.get("pool_address", "")[:20],
    )
    await stop.wait()

    job_event.set()
    maturity_stop.set()
    payouts.stop()
    jobs.stop()
    network.stop()
    validator.close()
    await stratum.stop()
    server.should_exit = True
    await api_task


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="BTX self-hosted mining pool")
    parser.add_argument("-c", "--config", default="config.yaml", help="Config file path")
    args = parser.parse_args(argv)

    try:
        cfg = load_config(args.config)
    except ValueError as e:
        print(f"Config error: {e}", file=sys.stderr)
        sys.exit(1)

    setup_logging(cfg.get("log_level", "INFO"))

    try:
        asyncio.run(run_pool(cfg))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
