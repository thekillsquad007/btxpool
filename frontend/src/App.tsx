import { useEffect, useState } from "react";
import "./App.css";

interface HashrateDisplay {
  display: string;
  raw?: number;
}

interface DurationDisplay {
  display: string;
  seconds: number | null;
}

interface PoolStats {
  network: {
    hashrate: HashrateDisplay;
    difficulty: number;
    next_difficulty: number;
    height: number;
    target: string;
    bits: string;
    chain: string;
    algorithm: string;
    matmul: { n: number; b: number; r: number };
    block_time: DurationDisplay;
    target_spacing_sec: number;
  };
  pool: {
    hashrate: HashrateDisplay;
    hashrate_10m: HashrateDisplay;
    difficulty: number;
    connected_miners: number;
    network_share_percent: number;
    block_time: DurationDisplay;
    share_interval: DurationDisplay;
    shares_10m: number;
  };
  job: {
    job_id: string;
    height: number;
  } | null;
}

interface PoolData {
  name: string;
  address: string;
  fee_percent: number;
  stratum_port: number;
  algorithm: string;
  totals: {
    miners: number;
    shares: number;
    total_work: number;
    blocks: number;
    rejected_shares: number;
  };
  chain: {
    synced: boolean;
    height: number;
    difficulty: number;
    network_difficulty: number;
    next_difficulty?: number;
    network_hashrate?: number;
    coinbasevalue?: number;
    target_spacing_sec?: number;
    current_job_id: string | null;
    last_error: string;
  };
  connected_miners: number;
  stats: PoolStats;
}

interface Miner {
  address: string;
  worker_name: string;
  canonical_name: string;
  last_seen: number;
  difficulty: number;
  shares_valid: number;
  shares_invalid: number;
  blocks_found: number;
  hashrate_estimate: number;
}

interface Share {
  address: string;
  worker_name: string;
  job_id: string;
  nonce64: string;
  difficulty: number;
  is_block: number;
  created_at: number;
}

interface Block {
  height: number;
  hash: string;
  finder_address: string;
  reward_sats: number;
  created_at: number;
}

function formatBtx(sats: number): string {
  return (sats / 1e8).toFixed(4);
}

function timeAgo(ts: number): string {
  const sec = Math.max(0, Math.floor(Date.now() / 1000 - ts));
  if (sec < 60) return `${sec}s ago`;
  if (sec < 3600) return `${Math.floor(sec / 60)}m ago`;
  return `${Math.floor(sec / 3600)}h ago`;
}

function truncate(addr: string, n = 12): string {
  if (addr.length <= n * 2 + 3) return addr;
  return `${addr.slice(0, n)}...${addr.slice(-n)}`;
}

function pctBar(value: number, max = 100): number {
  if (!Number.isFinite(value) || value <= 0) return 0;
  return Math.min(100, (value / max) * 100);
}

export default function App() {
  const [pool, setPool] = useState<PoolData | null>(null);
  const [miners, setMiners] = useState<Miner[]>([]);
  const [shares, setShares] = useState<Share[]>([]);
  const [blocks, setBlocks] = useState<Block[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    const load = async () => {
      try {
        const [p, m, s, b] = await Promise.all([
          fetch("/api/pool").then((r) => r.json()),
          fetch("/api/miners").then((r) => r.json()),
          fetch("/api/shares?limit=20").then((r) => r.json()),
          fetch("/api/blocks?limit=10").then((r) => r.json()),
        ]);
        setPool(p);
        setMiners(m.miners);
        setShares(s.shares);
        setBlocks(b.blocks);
        setError("");
      } catch {
        setError("Cannot reach pool API — is btxpool running?");
      }
    };
    load();
    const id = setInterval(load, 5000);
    return () => clearInterval(id);
  }, []);

  const host = window.location.hostname || "YOUR_SERVER_IP";
  const stats = pool?.stats;
  const netShare = stats?.pool.network_share_percent ?? 0;
  const blockReward = pool?.chain.coinbasevalue ?? 0;

  return (
    <div className="app">
      <header className="header">
        <div className="brand">
          <div className="logo">⛏</div>
          <div>
            <h1>{pool?.name ?? "BTX Pool"}</h1>
            <p className="subtitle">{pool?.algorithm ?? "MatMul PoW"} · Self-hosted</p>
          </div>
        </div>
        <div className="header-meta">
          <div className="status-pill">
            <span className={`dot ${pool?.chain.synced ? "online" : "syncing"}`} />
            {pool?.chain.synced ? "Mining active" : "Waiting for btxd sync"}
          </div>
          {stats?.job && (
            <div className="job-pill mono">{stats.job.job_id}</div>
          )}
        </div>
      </header>

      {error && <div className="banner error">{error}</div>}
      {pool?.chain.last_error && !pool.chain.synced && (
        <div className="banner warn">{pool.chain.last_error}</div>
      )}

      <section className="hero-stats">
        <div className="hero-card network">
          <span className="hero-label">Network hashrate</span>
          <span className="hero-value">{stats?.network.hashrate.display ?? "—"}</span>
          <span className="hero-sub">
            Diff {stats?.network.difficulty?.toFixed(6) ?? "—"}
            {stats?.network.next_difficulty ? (
              <> → {stats.network.next_difficulty.toFixed(6)} next</>
            ) : null}
          </span>
        </div>
        <div className="hero-card pool">
          <span className="hero-label">Pool hashrate</span>
          <span className="hero-value accent">{stats?.pool.hashrate.display ?? "0 H/s"}</span>
          <span className="hero-sub">
            {stats?.pool.shares_10m
              ? `${stats.pool.shares_10m} shares / 10m`
              : "Submit shares to estimate"}
          </span>
        </div>
        <div className="hero-card block">
          <span className="hero-label">Est. network block</span>
          <span className="hero-value">{stats?.network.block_time.display ?? "—"}</span>
          <span className="hero-sub">
            Target ~{Math.round(stats?.network.target_spacing_sec ?? 90)}s spacing
          </span>
        </div>
        <div className="hero-card reward">
          <span className="hero-label">Block reward</span>
          <span className="hero-value success">{blockReward ? `${formatBtx(blockReward)} BTX` : "—"}</span>
          <span className="hero-sub">Height {pool?.chain.height?.toLocaleString() ?? "—"}</span>
        </div>
      </section>

      <section className="insight-row">
        <div className="insight-card">
          <div className="insight-head">
            <h3>Pool vs network</h3>
            <span className="insight-pct">{netShare > 0 ? `${netShare.toFixed(3)}%` : "<0.001%"}</span>
          </div>
          <div className="progress-track">
            <div
              className="progress-fill pool-fill"
              style={{ width: `${Math.max(pctBar(netShare, 5), netShare > 0 ? 2 : 0)}%` }}
            />
          </div>
          <p className="insight-note">
            {stats?.pool.block_time.display && stats.pool.block_time.display !== "—"
              ? `Pool est. block time: ${stats.pool.block_time.display}`
              : "Connect miners to see pool block estimate"}
          </p>
        </div>

        <div className="insight-card">
          <div className="insight-head">
            <h3>Mining economics</h3>
          </div>
          <div className="metric-list">
            <MetricRow label="Pool difficulty" value={stats?.pool.difficulty?.toFixed(4) ?? "—"} />
            <MetricRow
              label="Share interval"
              value={stats?.pool.share_interval.display ?? "—"}
            />
            <MetricRow
              label="Network bits"
              value={stats?.network.bits ? `0x${stats.network.bits}` : "—"}
              mono
            />
            <MetricRow label="Connected rigs" value={String(pool?.connected_miners ?? 0)} />
          </div>
        </div>

        <div className="insight-card">
          <div className="insight-head">
            <h3>Algorithm</h3>
          </div>
          <div className="chip-row">
            <span className="chip">n={stats?.network.matmul.n ?? 512}</span>
            <span className="chip">b={stats?.network.matmul.b ?? 16}</span>
            <span className="chip">r={stats?.network.matmul.r ?? 8}</span>
            <span className="chip accent">{stats?.network.algorithm ?? "matmul"}</span>
          </div>
          <div className="metric-list">
            <MetricRow label="Valid shares" value={String(pool?.totals.shares ?? 0)} />
            <MetricRow label="Rejected" value={String(pool?.totals.rejected_shares ?? 0)} danger />
            <MetricRow label="Blocks found" value={String(pool?.totals.blocks ?? 0)} success />
            <MetricRow label="Registered miners" value={String(pool?.totals.miners ?? 0)} />
          </div>
        </div>
      </section>

      <section className="stats-grid">
        <StatCard label="Network difficulty" value={stats?.network.difficulty?.toFixed(6) ?? "—"} />
        <StatCard label="Pool hashrate (10m)" value={stats?.pool.hashrate_10m.display ?? "0 H/s"} />
        <StatCard label="Pool hashrate (est.)" value={stats?.pool.hashrate.display ?? "0 H/s"} accent />
        <StatCard label="Total work" value={(pool?.totals.total_work ?? 0).toFixed(2)} />
        <StatCard label="Next difficulty" value={stats?.network.next_difficulty?.toFixed(6) ?? "—"} />
        <StatCard label="Chain" value={stats?.network.chain ?? "main"} />
      </section>

      <section className="connect-card">
        <h2>Connect your miners</h2>
        <p>
          Compatible with{" "}
          <a href="https://github.com/thekillsquad007/amdbtx" target="_blank" rel="noreferrer">
            amdbtx
          </a>{" "}
          and{" "}
          <a href="https://github.com/thekillsquad007/btx-nvidia-miner" target="_blank" rel="noreferrer">
            btx-nvidia-miner
          </a>
          .
        </p>
        <div className="connect-rows">
          <ConnectRow label="Stratum URL" value={`stratum+tcp://${host}:${pool?.stratum_port ?? 3333}`} />
          <ConnectRow label="Username" value="Your btx1z... payout address" />
          <ConnectRow label="Password" value="x (or empty)" />
        </div>
        <pre className="miner-config">{`# btx-nvidia-miner
btx-miner --pool stratum+tcp://${host}:${pool?.stratum_port ?? 3333} \\
  --user btx1z...YOUR_ADDRESS.rig01 --pass x --devices all`}</pre>
      </section>

      <div className="panels">
        <Panel title="Miners">
          {miners.length === 0 ? (
            <EmptyState text="No miners connected yet" />
          ) : (
            <table>
              <thead>
                <tr>
                  <th>Worker</th>
                  <th>Shares</th>
                  <th>Rejected</th>
                  <th>Est. H/s</th>
                  <th>Last seen</th>
                </tr>
              </thead>
              <tbody>
                {miners.map((m) => (
                  <tr key={m.address}>
                    <td className="mono">{truncate(m.canonical_name || m.address, 8)}</td>
                    <td>{m.shares_valid}</td>
                    <td className={m.shares_invalid > 0 ? "danger" : ""}>{m.shares_invalid}</td>
                    <td className="muted">
                      {m.hashrate_estimate > 0 ? m.hashrate_estimate.toFixed(4) : "—"}
                    </td>
                    <td className="muted">{timeAgo(m.last_seen)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Panel>

        <Panel title="Recent shares">
          {shares.length === 0 ? (
            <EmptyState text="Shares will appear here once miners submit" />
          ) : (
            <table>
              <thead>
                <tr>
                  <th>Miner</th>
                  <th>Job</th>
                  <th>Diff</th>
                  <th>When</th>
                </tr>
              </thead>
              <tbody>
                {shares.map((s, i) => (
                  <tr key={i} className={s.is_block ? "block-row" : ""}>
                    <td className="mono">{truncate(s.address, 6)}</td>
                    <td className="mono muted">{s.job_id.slice(0, 18)}...</td>
                    <td>{s.difficulty.toFixed(4)}</td>
                    <td className="muted">{timeAgo(s.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Panel>
      </div>

      {blocks.length > 0 && (
        <Panel title="Blocks found">
          <table>
            <thead>
              <tr>
                <th>Height</th>
                <th>Finder</th>
                <th>Reward</th>
                <th>When</th>
              </tr>
            </thead>
            <tbody>
              {blocks.map((b, i) => (
                <tr key={i}>
                  <td>{b.height}</td>
                  <td className="mono">{truncate(b.finder_address, 8)}</td>
                  <td className="success">{formatBtx(b.reward_sats)} BTX</td>
                  <td className="muted">{timeAgo(b.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>
      )}

      <footer className="footer">
        <span>
          Pool address: <code>{pool?.address ? truncate(pool.address, 10) : "—"}</code>
        </span>
        <span>Fee: {pool?.fee_percent ?? 0}%</span>
        <a href="https://github.com/btxchain/btx" target="_blank" rel="noreferrer">
          BTX Chain
        </a>
      </footer>
    </div>
  );
}

function StatCard({ label, value, accent }: { label: string; value: string; accent?: boolean }) {
  return (
    <div className={`stat-card ${accent ? "accent" : ""}`}>
      <span className="stat-label">{label}</span>
      <span className="stat-value">{value}</span>
    </div>
  );
}

function MetricRow({
  label,
  value,
  mono,
  danger,
  success,
}: {
  label: string;
  value: string;
  mono?: boolean;
  danger?: boolean;
  success?: boolean;
}) {
  return (
    <div className="metric-row">
      <span className="metric-label">{label}</span>
      <span className={`metric-value ${mono ? "mono" : ""} ${danger ? "danger" : ""} ${success ? "success" : ""}`}>
        {value}
      </span>
    </div>
  );
}

function ConnectRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="connect-row">
      <span className="connect-label">{label}</span>
      <code className="connect-value">{value}</code>
    </div>
  );
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="panel">
      <h3>{title}</h3>
      {children}
    </section>
  );
}

function EmptyState({ text }: { text: string }) {
  return <p className="empty">{text}</p>;
}