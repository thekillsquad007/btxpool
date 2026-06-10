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
from pool.stats import build_dashboard_stats


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
                "share_target": job.share_target[:16] + "...",
                "matmul_n": job.matmul_n,
                "matmul_b": job.matmul_b,
                "matmul_r": job.matmul_r,
            }
        matmul = net.get("matmul") or {}
        algorithm = (
            f"MatMul PoW (n={matmul.get('n', 512)}, "
            f"b={matmul.get('b', 16)}, r={matmul.get('r', 8)})"
        )
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
        }

    @app.get("/api/miners")
    def miners():
        return {"miners": db.list_miners()}

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
        return {
            "job": {
                "job_id": job.job_id,
                "height": job.block_height,
                "prev_hash": job.prev_hash,
                "difficulty": jobs.difficulty,
                "share_target": job.share_target[:16] + "...",
            },
            "status": jobs.status(),
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