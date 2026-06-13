"""HTTP API for the pool dashboard."""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from pool.database import PoolDatabase
from pool.job_manager import JobManager
from pool.network_monitor import NetworkMonitor
from pool.stats import (
    annotate_worker_hashrate,
    block_find_luck_percent,
    block_time_seconds,
    build_dashboard_stats,
    build_mining_context,
)

SATS_PER_BTX = 100_000_000
WALLET_ADDRESS_RE = re.compile(r"^btx1[a-z0-9]{50,120}$", re.IGNORECASE)


def _next_payout_eta(
    cfg: dict[str, Any], db: PoolDatabase, payouts=None
) -> float | None:
    if payouts and payouts.next_run_at:
        return float(payouts.next_run_at)
    last = db.get_stat("last_payout_at", "")
    if not last:
        return None
    try:
        last_ts = float(last)
    except ValueError:
        return None
    interval = float(cfg.get("payout_interval_hours", 24)) * 3600.0
    return last_ts + interval


def _share_quality(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    ratio = float(row.get("block_ratio") or 0)
    result = dict(row)
    result["block_percent"] = ratio * 100.0
    result["times_above_target"] = (1.0 / ratio) if ratio > 0 else None
    return result


def create_app(
    cfg: dict[str, Any],
    db: PoolDatabase,
    jobs: JobManager,
    stratum_sessions: callable,
    network: NetworkMonitor | None = None,
    payouts=None,
    stratum_status: callable | None = None,
) -> FastAPI:
    app = FastAPI(title=cfg.get("pool_name", "BTX Pool"), version="0.1.0")
    cors_origins = cfg.get("cors_origins") or []
    if isinstance(cors_origins, str):
        cors_origins = [
            origin.strip() for origin in cors_origins.split(",") if origin.strip()
        ]
    if cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_methods=["GET"],
            allow_headers=["Accept", "Content-Type"],
        )

    @app.get("/api/health")
    def health():
        job_status = jobs.status()
        capacity = stratum_status() if stratum_status else {}
        ready = bool(job_status.get("synced") and jobs.current_job)
        return {
            "status": "ok" if ready else "degraded",
            "ready": ready,
            "chain": job_status,
            "capacity": capacity,
            "unresolved_payouts": len(db.unresolved_payouts()),
        }

    @app.get("/metrics", response_class=PlainTextResponse)
    def metrics():
        totals = db.totals()
        job_status = jobs.status()
        capacity = stratum_status() if stratum_status else {}
        best_share = db.best_share()
        best_ratio = float(best_share.get("block_ratio") or 0) if best_share else 0
        ready = 1 if job_status.get("synced") and jobs.current_job else 0
        lines = [
            "# HELP btxpool_ready Pool has a current mining job.",
            "# TYPE btxpool_ready gauge",
            f"btxpool_ready {ready}",
            "# HELP btxpool_connected_sessions Connected Stratum sessions.",
            "# TYPE btxpool_connected_sessions gauge",
            f"btxpool_connected_sessions {capacity.get('connected_sessions', 0)}",
            "# HELP btxpool_authorized_sessions Authorized Stratum sessions.",
            "# TYPE btxpool_authorized_sessions gauge",
            f"btxpool_authorized_sessions {capacity.get('authorized_sessions', 0)}",
            "# HELP btxpool_verifier_pending Shares waiting or being verified.",
            "# TYPE btxpool_verifier_pending gauge",
            f"btxpool_verifier_pending {capacity.get('verifier_pending', 0)}",
            "# HELP btxpool_verifier_queue_limit Maximum pending shares.",
            "# TYPE btxpool_verifier_queue_limit gauge",
            f"btxpool_verifier_queue_limit {capacity.get('verifier_queue_limit', 0)}",
            "# HELP btxpool_verifier_average_seconds Average verification latency.",
            "# TYPE btxpool_verifier_average_seconds gauge",
            f"btxpool_verifier_average_seconds {float(capacity.get('verifier_average_ms', 0)) / 1000.0}",
            "# HELP btxpool_verifier_overload_rejections_total Overload rejections.",
            "# TYPE btxpool_verifier_overload_rejections_total counter",
            f"btxpool_verifier_overload_rejections_total {capacity.get('verifier_overload_rejections', 0)}",
            "# HELP btxpool_shares_accepted_total Persisted accepted shares.",
            "# TYPE btxpool_shares_accepted_total counter",
            f"btxpool_shares_accepted_total {totals.get('shares', 0)}",
            "# HELP btxpool_shares_rejected_total Rejected shares.",
            "# TYPE btxpool_shares_rejected_total counter",
            f"btxpool_shares_rejected_total {totals.get('rejected_shares', 0)}",
            "# HELP btxpool_blocks_found_total Pool blocks found.",
            "# TYPE btxpool_blocks_found_total counter",
            f"btxpool_blocks_found_total {totals.get('blocks', 0)}",
            "# HELP btxpool_best_share_block_ratio Best accepted share versus the network block target; 1 is a block.",
            "# TYPE btxpool_best_share_block_ratio gauge",
            f"btxpool_best_share_block_ratio {best_ratio}",
            "# HELP btxpool_unresolved_payouts Reserved or uncertain payouts.",
            "# TYPE btxpool_unresolved_payouts gauge",
            f"btxpool_unresolved_payouts {len(db.unresolved_payouts())}",
        ]
        return "\n".join(lines) + "\n"

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
                "version": job.version,
                "height": job.block_height,
                "prev_hash": job.prev_hash,
                "merkle_root": job.merkle_root,
                "time": job.time,
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
        )
        pool_hash_hs = float(dashboard["pool"]["hashrate"].get("raw") or 0)
        net_diff = float(net.get("difficulty") or 0)
        round_start = db.round_start_time()
        round_stats = db.work_since(round_start)
        best_share_round = _share_quality(db.best_share(round_start))
        best_share_all_time = _share_quality(db.best_share())
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
        next_payout = _next_payout_eta(cfg, db, payouts)
        capacity = stratum_status() if stratum_status else {}
        block_summary = db.block_summary()
        return {
            "name": cfg.get("pool_name", "BTX Pool"),
            "address": cfg.get("pool_address", ""),
            "fee_percent": cfg.get("pool_fee_percent", 0),
            "dev_fee_address": cfg.get("dev_fee_address", ""),
            "payment_mode": cfg.get("payment_mode", "pplns"),
            "min_payout_btx": int(cfg.get("min_payout_sats", 500_000_000)) / SATS_PER_BTX,
            "payout_interval_hours": cfg.get("payout_interval_hours", 24),
            "payout_initial_delay_hours": cfg.get("payout_initial_delay_hours", 24),
            "coinbase_maturity": cfg.get("coinbase_maturity", 200),
            "payout_max_address_btx": int(
                cfg.get("payout_max_address_sats", 2_500_000_000)
            ) / SATS_PER_BTX,
            "payout_daily_limit_btx": int(
                cfg.get("payout_daily_limit_sats", 10_000_000_000)
            ) / SATS_PER_BTX,
            "payout_wallet_reserve_btx": int(
                cfg.get("payout_wallet_reserve_sats", 100_000_000)
            ) / SATS_PER_BTX,
            "next_payout_eta": next_payout,
            "payout_enabled": bool(cfg.get("payout_enabled", True)),
            "payout_dry_run": bool(cfg.get("payout_dry_run", False)),
            "stratum_port": cfg.get("stratum_port", 3333),
            "algorithm": algorithm,
            "totals": totals,
            "blocks": block_summary,
            "best_shares": {
                "round": best_share_round,
                "all_time": best_share_all_time,
                "tracking_since": (
                    float(db.get_stat("best_share_tracking_since", "0") or 0)
                    or None
                ),
            },
            "chain": {
                **job_status,
                "network_difficulty": net.get("difficulty", job_status.get("difficulty")),
                "next_difficulty": net.get("next_difficulty"),
                "network_hashrate": net.get("networkhashps", 0),
                "coinbasevalue": net.get("coinbasevalue", 0),
                "target_spacing_sec": net.get("target_spacing_sec", 90),
            },
            "connected_miners": stratum_sessions(),
            "operations": {
                "ready": bool(job_status.get("synced") and job),
                "capacity": capacity,
                "unresolved_payouts": len(db.unresolved_payouts()),
            },
            "stats": dashboard,
            "mining": mining,
        }

    @app.get("/api/miners")
    def miners():
        rows = db.list_miners()
        pool_diff = float(jobs.difficulty)
        epsilon_bits = int(jobs.current_job.epsilon_bits) if jobs.current_job else 18
        for row in rows:
            work_10m = db.worker_work_window(
                row["address"], row["worker_name"], 600.0
            )
            annotate_worker_hashrate(
                row,
                shares_10m=work_10m["shares"],
                window_sec=work_10m["window_sec"],
                pool_difficulty=pool_diff,
                epsilon_bits=epsilon_bits,
            )
        return {"miners": rows}

    @app.get("/api/shares")
    def shares(limit: int = 50):
        return {
            "best": {
                "round": _share_quality(db.best_share(db.round_start_time())),
                "all_time": _share_quality(db.best_share()),
            },
            "shares": [
                _share_quality(row) for row in db.recent_shares(limit)
            ],
        }

    @app.get("/api/blocks")
    def blocks(limit: int = 20):
        return {
            "summary": db.block_summary(),
            "blocks": db.recent_blocks(limit),
        }

    @app.get("/api/rounds")
    def rounds(limit: int = 20):
        return {"rounds": db.recent_rounds(limit)}

    @app.get("/api/payouts")
    def payout_history(address: str | None = None, limit: int = 50):
        return {"payouts": db.recent_payouts(address=address, limit=limit)}

    @app.get("/api/wallet/{address}")
    def wallet_dashboard(address: str):
        if not WALLET_ADDRESS_RE.match(address):
            raise HTTPException(status_code=400, detail="Invalid BTX wallet address")
        balance = db.get_balance(address)
        workers = db.miners_for_address(address)
        pool_diff = float(jobs.difficulty)
        epsilon_bits = int(jobs.current_job.epsilon_bits) if jobs.current_job else 18
        for row in workers:
            work_10m = db.worker_work_window(
                row["address"], row["worker_name"], 600.0
            )
            annotate_worker_hashrate(
                row,
                shares_10m=work_10m["shares"],
                window_sec=work_10m["window_sec"],
                pool_difficulty=pool_diff,
                epsilon_bits=epsilon_bits,
            )

        immature = int(balance["immature_sats"]) if balance else 0
        payable = int(balance["balance_sats"]) if balance else 0
        paid_total = int(balance["paid_total_sats"]) if balance else 0
        next_payout = _next_payout_eta(cfg, db, payouts)
        if next_payout is None:
            next_payout = time.time() + float(cfg.get("payout_interval_hours", 24)) * 3600.0

        return {
            "address": address,
            "balance_sats": payable,
            "balance_btx": payable / SATS_PER_BTX,
            "immature_sats": immature,
            "immature_btx": immature / SATS_PER_BTX,
            "paid_total_sats": paid_total,
            "paid_total_btx": paid_total / SATS_PER_BTX,
            "workers": workers,
            "recent_credits": db.recent_credits_for_address(address, limit=20),
            "recent_payouts": db.recent_payouts(address=address, limit=20),
            "payment_mode": cfg.get("payment_mode", "pplns"),
            "pool_fee_percent": cfg.get("pool_fee_percent", 0),
            "min_payout_btx": int(cfg.get("min_payout_sats", 500_000_000)) / SATS_PER_BTX,
            "payout_interval_hours": cfg.get("payout_interval_hours", 24),
            "next_payout_eta": next_payout,
        }

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
