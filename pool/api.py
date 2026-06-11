"""HTTP API for the pool dashboard."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from pool.database import PoolDatabase
from pool.job_manager import JobManager
from pool.network_monitor import NetworkMonitor
from pool.stats import (
    block_find_luck_percent,
    block_time_seconds,
    build_dashboard_stats,
    build_mining_context,
    format_hashrate,
)


def create_app(
    cfg: dict[str, Any],
    db: PoolDatabase,
    jobs: JobManager,
    stratum_sessions: callable,
    network: NetworkMonitor | None = None,
) -> FastAPI:
    app = FastAPI(title=cfg.get("pool_name", "BTX Pool"), version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    @app.get("/api/pool")
    def pool_stats():
        totals = db.totals()
        job_status = jobs.status()
        net = network.snapshot() if network else {}
        work_10m = db.work_window(600)
        work_1h = db.work_window(3600)
        job = jobs.current_job
        job_info = None
        if job:
            job_info = {
                "job_id": job.job_id,
                "height": job.block_height,
                "prev_hash": job.prev_hash,
                "merkle_root": job.merkle_root,
                "bits": job.bits,
                "block_target": job.block_target,
                "share_target": job.share_target,
                "seed_a": job.seed_a,
                "seed_b": job.seed_b,
                "matmul_n": job.matmul_n,
                "matmul_b": job.matmul_b,
                "matmul_r": job.matmul_r,
                "epsilon_bits": job.epsilon_bits,
            }
        matmul = net.get("matmul") or {}
        algorithm = (
            f"MatMul PoW (n={matmul.get('n', 512)}, "
            f"b={matmul.get('b', 16)}, r={matmul.get('r', 8)})"
        )
        pool_hashrate_metrics = db.active_hashrate_sum()
        dashboard = build_dashboard_stats(
            network=net,
            pool_work={
                "work_10m": work_10m["work"],
                "shares_10m": work_10m["shares"],
                "window_10m": work_10m["window_sec"],
                "work_1h": work_1h["work"],
                "shares_1h": work_1h["shares"],
                "window_1h": work_1h["window_sec"],
            },
            pool_difficulty=jobs.difficulty,
            connected_miners=stratum_sessions(),
            totals=totals,
            job=job_info,
            pool_hashrate_metrics=pool_hashrate_metrics,
            hashrate_source="metrics" if pool_hashrate_metrics > 0 else "shares",
        )
        pool_hash_hs = float(dashboard["pool"]["hashrate"].get("raw") or 0)
        net_diff = float(net.get("difficulty") or 0)
        round_start = db.round_start_time()
        round_stats = db.work_since(round_start)
        last_block_row = db.last_block()
        last_block_info = dict(last_block_row) if last_block_row else None
        if last_block_info and pool_hash_hs > 0 and net_diff > 0:
            blocks = db.recent_blocks(2)
            if len(blocks) >= 2:
                interval = float(blocks[0]["created_at"]) - float(blocks[1]["created_at"])
                expected = block_time_seconds(net_diff, pool_hash_hs)
                luck = block_find_luck_percent(interval, expected) if expected else None
                if luck is not None:
                    last_block_info["luck_percent"] = round(luck, 1)
        mining = build_mining_context(
            job=job_info,
            chain_synced=bool(job_status.get("synced")),
            chain_tip_height=int(net.get("height") or job_status.get("height") or 0),
            rpc_url=cfg.get("rpc_url", ""),
            pool_hashrate_hs=pool_hash_hs,
            network_hashrate_hs=float(net.get("networkhashps") or 0),
            network_difficulty=net_diff,
            share_interval_sec=dashboard["pool"].get("share_interval_seconds"),
            round_start_ts=round_start,
            round_shares=round_stats["shares"],
            round_work=round_stats["work"],
            last_block=last_block_info,
        )
        return {
            "name": cfg.get("pool_name", "BTX Pool"),
            "address": cfg.get("pool_address", ""),
            "fee_percent": cfg.get("pool_fee_percent", 0),
            "stratum_port": cfg.get("stratum_port", 3333),
            "algorithm": algorithm,
            "totals": totals,
            "chain": {
                **job_status,
                "network_difficulty": net.get("difficulty", job_status.get("difficulty")),
                "next_difficulty": net.get("next_difficulty"),
                "network_hashrate": net.get("networkhashps", 0),
                "coinbasevalue": net.get("coinbasevalue", 0),
                "target_spacing_sec": net.get("target_spacing_sec", 90),
            },
            "connected_miners": stratum_sessions(),
            "stats": dashboard,
            "mining": mining,
        }

    @app.get("/api/miners")
    def miners():
        rows = db.list_miners()
        for row in rows:
            row["hashrate"] = format_hashrate(float(row.get("hashrate_estimate") or 0))
        return {"miners": rows}

    @app.get("/api/shares")
    def shares(limit: int = 50):
        return {"shares": db.recent_shares(limit)}

    @app.get("/api/blocks")
    def blocks(limit: int = 20):
        return {"blocks": db.recent_blocks(limit)}

    @app.get("/api/job")
    def current_job():
        job = jobs.current_job
        if not job:
            return {"job": None, "status": jobs.status()}
        status = jobs.status()
        job_info = {
            "job_id": job.job_id,
            "height": job.block_height,
            "prev_hash": job.prev_hash,
            "merkle_root": job.merkle_root,
            "bits": job.bits,
            "difficulty": jobs.difficulty,
            "block_target": job.block_target,
            "share_target": job.share_target,
            "seed_a": job.seed_a,
            "seed_b": job.seed_b,
            "matmul_n": job.matmul_n,
            "matmul_b": job.matmul_b,
            "matmul_r": job.matmul_r,
            "epsilon_bits": job.epsilon_bits,
        }
        return {
            "job": job_info,
            "status": status,
            "mining": build_mining_context(
                job=job_info,
                chain_synced=bool(status.get("synced")),
                chain_tip_height=int(status.get("height") or 0),
                rpc_url=cfg.get("rpc_url", ""),
            ),
        }

    frontend_dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
    if frontend_dist.is_dir():
        app.mount("/assets", StaticFiles(directory=frontend_dist / "assets"), name="assets")

        @app.get("/")
        def index():
            return FileResponse(frontend_dist / "index.html")

        @app.get("/{path:path}")
        def spa(path: str):
            target = frontend_dist / path
            if target.is_file():
                return FileResponse(target)
            return FileResponse(frontend_dist / "index.html")

    return app