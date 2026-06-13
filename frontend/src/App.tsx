import { useEffect, useState } from "react";
import { apiUrl } from "./api";
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
    hashrate_gate?: HashrateDisplay;
    hashrate_gate_10m?: HashrateDisplay;
    reported_nonce_rate?: HashrateDisplay;
    reported_gate_rate?: HashrateDisplay;
    hashrate_source?: string;
    epsilon_bits: number;
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

interface TargetRatio {
  ratio: number;
  display: string;
  log10: number;
}

interface BlockProgress {
  progress_percent: number;
  progress_display: string;
  bar_fill_percent: number;
  luck_status: string;
  luck_message: string;
  round_elapsed: DurationDisplay;
  expected_block_time: DurationDisplay;
  median_block_time: DurationDisplay;
  p95_block_time: DurationDisplay;
  remaining_block_time: DurationDisplay;
  round_shares: number;
  round_work: number;
  last_block_height: number | null;
  last_block_luck_percent: number | null;
}

interface MiningContext {
  active: boolean;
  synced: boolean;
  rpc_source: string;
  message: string;
  mining_height?: number;
  chain_tip_height?: number;
  job_id?: string;
  prev_hash?: string;
  merkle_root?: string;
  bits?: string;
  block_target?: string;
  share_target?: string;
  seed_a?: string;
  seed_b?: string;
  matmul_n?: number;
  epsilon_bits?: number;
  share_easier?: TargetRatio;
  can_find_blocks?: boolean;
  block_submit_path?: string;
  est_pool_block_time?: DurationDisplay;
  network_block_time?: DurationDisplay;
  block_progress?: BlockProgress;
}

interface PoolData {
  name: string;
  address: string;
  fee_percent: number;
  payment_mode?: string;
  min_payout_btx?: number;
  payout_interval_hours?: number;
  payout_initial_delay_hours?: number;
  coinbase_maturity?: number;
  payout_max_address_btx?: number;
  payout_daily_limit_btx?: number;
  payout_wallet_reserve_btx?: number;
  next_payout_eta?: number | null;
  payout_enabled?: boolean;
  payout_dry_run?: boolean;
  stratum_port: number;
  algorithm: string;
  totals: {
    miners: number;
    shares: number;
    total_work: number;
    blocks: number;
    rejected_shares: number;
  };
  blocks?: BlockSummary;
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
  operations?: {
    ready: boolean;
    unresolved_payouts: number;
    capacity: {
      connected_sessions: number;
      authorized_sessions: number;
      verifier_workers: number;
      verifier_pending: number;
      verifier_queue_limit: number;
      verifier_utilization_percent: number;
      verifier_completed: number;
      verifier_overload_rejections: number;
      verifier_average_ms: number;
    };
  };
  stats: PoolStats;
  mining?: MiningContext;
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
  hashrate?: HashrateDisplay;
  hashrate_nonce_reported?: HashrateDisplay;
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
  distributable_sats: number;
  status: string;
  confirmations: number;
  created_at: number;
}

interface BlockSummary {
  total: number;
  immature: number;
  credited: number;
  orphaned: number;
  latest: Block | null;
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

function truncateHex(hex: string, head = 16, tail = 8): string {
  if (!hex || hex.length <= head + tail + 3) return hex || "—";
  return `${hex.slice(0, head)}…${hex.slice(-tail)}`;
}

function targetBarWidth(log10: number, maxLog10: number): number {
  if (!Number.isFinite(log10) || log10 <= 0) return 4;
  return Math.max(4, Math.min(100, (log10 / maxLog10) * 100));
}

interface WalletData {
  address: string;
  balance_btx: number;
  immature_btx: number;
  paid_total_btx: number;
  workers: Miner[];
  recent_credits: Array<{
    round_id: number;
    amount_sats: number;
    height: number;
    created_at: number;
    status: string;
  }>;
  recent_payouts: Array<{
    amount_sats: number;
    txid: string;
    status: string;
    created_at: number;
  }>;
  min_payout_btx: number;
  payout_interval_hours: number;
  next_payout_eta: number;
  pool_fee_percent: number;
  payment_mode: string;
}

function walletFromPath(): string | null {
  const match = window.location.pathname.match(/^\/wallet\/([^/]+)\/?$/i);
  return match ? decodeURIComponent(match[1]) : null;
}

function WalletDashboard({ address }: { address: string }) {
  const [wallet, setWallet] = useState<WalletData | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    const load = async () => {
      try {
        const res = await fetch(apiUrl(`/api/wallet/${encodeURIComponent(address)}`));
        if (!res.ok) {
          const body = await res.json().catch(() => ({}));
          throw new Error(body.detail || res.statusText);
        }
        setWallet(await res.json());
        setError("");
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to load wallet");
      }
    };
    load();
    const id = setInterval(load, 10000);
    return () => clearInterval(id);
  }, [address]);

  const nextPayout = wallet?.next_payout_eta
    ? new Date(wallet.next_payout_eta * 1000).toLocaleString()
    : "—";

  return (
    <div className="app">
      <header className="header">
        <div className="brand">
          <div className="logo">⛏</div>
          <div>
            <h1>Miner wallet</h1>
            <p className="subtitle mono">{truncate(address, 14)}</p>
          </div>
        </div>
        <a className="wallet-back" href="/">← Pool dashboard</a>
      </header>

      {error && <div className="banner error">{error}</div>}

      {wallet && (
        <>
          <section className="hero-stats wallet-stats">
            <div className="hero-card pool">
              <span className="hero-label">Payable balance</span>
              <span className="hero-value accent">{wallet.balance_btx.toFixed(4)} BTX</span>
              <span className="hero-sub">Min payout {wallet.min_payout_btx} BTX</span>
            </div>
            <div className="hero-card block">
              <span className="hero-label">Immature</span>
              <span className="hero-value">{wallet.immature_btx.toFixed(4)} BTX</span>
              <span className="hero-sub">Awaiting coinbase maturity</span>
            </div>
            <div className="hero-card reward">
              <span className="hero-label">Total paid</span>
              <span className="hero-value success">{wallet.paid_total_btx.toFixed(4)} BTX</span>
              <span className="hero-sub">{wallet.payment_mode.toUpperCase()} · {wallet.pool_fee_percent}% fee</span>
            </div>
            <div className="hero-card network">
              <span className="hero-label">Next payout</span>
              <span className="hero-value">{nextPayout}</span>
              <span className="hero-sub">Every {wallet.payout_interval_hours}h</span>
            </div>
          </section>

          <div className="panels">
            <Panel title="Workers">
              {wallet.workers.length === 0 ? (
                <EmptyState text="No workers registered for this wallet yet" />
              ) : (
                <table>
                  <thead>
                    <tr>
                      <th>Worker</th>
                      <th>Shares</th>
                      <th>Rejected</th>
                      <th>Pool N/s</th>
                      <th>Last seen</th>
                    </tr>
                  </thead>
                  <tbody>
                    {wallet.workers.map((m) => (
                      <tr key={m.canonical_name || m.address}>
                        <td className="mono">{m.worker_name || m.canonical_name}</td>
                        <td>{m.shares_valid}</td>
                        <td className={m.shares_invalid > 0 ? "danger" : ""}>{m.shares_invalid}</td>
                        <td className="muted">{m.hashrate?.display ?? "—"}</td>
                        <td className="muted">{timeAgo(m.last_seen)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </Panel>

            <Panel title="Recent PPLNS credits">
              {wallet.recent_credits.length === 0 ? (
                <EmptyState text="Credits appear when the pool finds a block" />
              ) : (
                <table>
                  <thead>
                    <tr>
                      <th>Height</th>
                      <th>Amount</th>
                      <th>Status</th>
                      <th>When</th>
                    </tr>
                  </thead>
                  <tbody>
                    {wallet.recent_credits.map((c) => (
                      <tr key={`${c.round_id}-${c.created_at}`}>
                        <td>{c.height}</td>
                        <td className="success">{formatBtx(c.amount_sats)} BTX</td>
                        <td className="muted">{c.status}</td>
                        <td className="muted">{timeAgo(c.created_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </Panel>
          </div>

          {wallet.recent_payouts.length > 0 && (
            <Panel title="Payout history">
              <table>
                <thead>
                  <tr>
                    <th>Amount</th>
                    <th>TxID</th>
                    <th>Status</th>
                    <th>When</th>
                  </tr>
                </thead>
                <tbody>
                  {wallet.recent_payouts.map((p, i) => (
                    <tr key={i}>
                      <td className="success">{formatBtx(p.amount_sats)} BTX</td>
                      <td className="mono muted">{truncate(p.txid || "—", 8)}</td>
                      <td>{p.status}</td>
                      <td className="muted">{timeAgo(p.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Panel>
          )}
        </>
      )}
    </div>
  );
}

export default function App() {
  const walletAddress = walletFromPath();
  const monitoringPath = /^\/monitoring\/?$/i.test(window.location.pathname);
  const [pool, setPool] = useState<PoolData | null>(null);
  const [miners, setMiners] = useState<Miner[]>([]);
  const [shares, setShares] = useState<Share[]>([]);
  const [blocks, setBlocks] = useState<Block[]>([]);
  const [blockSummary, setBlockSummary] = useState<BlockSummary | null>(null);
  const [error, setError] = useState("");
  const [lookupAddress, setLookupAddress] = useState("");

  useEffect(() => {
    const load = async () => {
      try {
        const [p, m, s, b] = await Promise.all([
          fetch(apiUrl("/api/pool")).then((r) => r.json()),
          fetch(apiUrl("/api/miners")).then((r) => r.json()),
          fetch(apiUrl("/api/shares?limit=20")).then((r) => r.json()),
          fetch(apiUrl("/api/blocks?limit=10")).then((r) => r.json()),
        ]);
        setPool(p);
        setMiners(m.miners);
        setShares(s.shares);
        setBlocks(b.blocks);
        setBlockSummary(b.summary ?? null);
        setError("");
      } catch {
        setError("Cannot reach pool API — is btxpool running?");
      }
    };
    load();
    const id = setInterval(load, 5000);
    return () => clearInterval(id);
  }, []);

  if (walletAddress) {
    return <WalletDashboard address={walletAddress} />;
  }

  const host = window.location.hostname || "YOUR_SERVER_IP";
  const stats = pool?.stats;
  const mining = pool?.mining;
  const netShare = stats?.pool.network_share_percent ?? 0;
  const blockReward = pool?.chain.coinbasevalue ?? 0;
  const targetLog10 = mining?.share_easier?.log10 ?? 8;
  const blockProgress = mining?.block_progress;
  const totalSubmissions =
    (pool?.totals.shares ?? 0) + (pool?.totals.rejected_shares ?? 0);
  const rejectionRate = totalSubmissions
    ? ((pool?.totals.rejected_shares ?? 0) / totalSubmissions) * 100
    : 0;
  const capacity = pool?.operations?.capacity;
  const payoutStatus = !pool?.payout_enabled
    ? "Disabled"
    : pool?.payout_dry_run
      ? "Dry run"
      : "Automatic";
  const latestBlock = blockSummary?.latest ?? pool?.blocks?.latest ?? null;
  const blocksFound =
    blockSummary?.total ?? pool?.blocks?.total ?? pool?.totals.blocks ?? 0;

  return (
    <div className={`app ${monitoringPath ? "monitoring-view" : "public-view"}`}>
      <header className="header">
        <div className="brand">
          <div className="logo">BTX</div>
          <div>
            <h1>{pool?.name ?? "BTX Pool"}</h1>
            <p className="subtitle">{pool?.algorithm ?? "MatMul PoW"} · PPLNS mining</p>
          </div>
        </div>
        <div className="header-meta">
          <nav className="page-nav" aria-label="Pool navigation">
            <a className={!monitoringPath ? "active" : ""} href="/">Pool</a>
            <a className={monitoringPath ? "active" : ""} href="/monitoring">Monitoring</a>
          </nav>
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

      {monitoringPath && (
        <section className="monitoring-intro">
          <div>
            <span className="eyebrow">Operations console</span>
            <h2>Pool monitoring</h2>
            <p>Node state, verifier capacity, share quality, mining targets, and recent submissions.</p>
          </div>
          <a className="secondary-action" href="/">Back to public pool page</a>
        </section>
      )}

      <section className="production-hero">
        <div className="production-copy">
          <span className="eyebrow">BTX MatMul mining pool</span>
          <h2>Transparent PPLNS mining with live share accounting.</h2>
          <p>
            Connect AMD or NVIDIA rigs, track each worker, and view pool work,
            block probability, balances, and payout history from one dashboard.
          </p>
          <div className="hero-actions">
            <a className="primary-action" href="#connect">Connect a miner</a>
            <a className="secondary-action" href="/monitoring">View monitoring</a>
          </div>
        </div>
        <div className="production-endpoint">
          <span className="endpoint-label">Stratum endpoint</span>
          <code>{`stratum+tcp://${host}:${pool?.stratum_port ?? 3333}`}</code>
          <span className="endpoint-note">
            Username: your BTX address, optionally followed by a worker name
          </span>
        </div>
      </section>

      <section className="operations-strip" id="pool-health">
        <OperationalCard
          label="Pool status"
          value={pool?.operations?.ready ? "Ready" : "Degraded"}
          tone={pool?.operations?.ready ? "good" : "warn"}
          note={pool?.chain.synced ? `Chain height ${pool.chain.height.toLocaleString()}` : "Waiting for a current job"}
        />
        <OperationalCard
          label="Share verifier"
          value={capacity ? `${capacity.verifier_pending} / ${capacity.verifier_queue_limit}` : "Loading"}
          tone={(capacity?.verifier_utilization_percent ?? 0) >= 80 ? "warn" : "good"}
          note={capacity ? `${capacity.verifier_workers} workers, ${capacity.verifier_average_ms.toFixed(1)} ms average` : "Queue utilization"}
        />
        <OperationalCard
          label="Share quality"
          value={`${rejectionRate.toFixed(2)}% rejected`}
          tone={rejectionRate > 5 ? "warn" : "good"}
          note={`${pool?.totals.shares ?? 0} accepted shares`}
        />
        <OperationalCard
          label="Payout mode"
          value={payoutStatus}
          tone={pool?.payout_enabled && !pool?.payout_dry_run ? "good" : "neutral"}
          note={`${pool?.coinbase_maturity ?? 200} confirmations / ${pool?.min_payout_btx ?? 5} BTX min / ${pool?.payout_max_address_btx ?? 25} BTX cap`}
        />
      </section>

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
          <span className="hero-value accent">{stats?.pool.hashrate.display ?? "0 N/s"}</span>
          <span className="hero-sub">
            {stats?.pool.hashrate.raw
              ? `${stats.pool.network_share_percent?.toFixed(3) ?? "0"}% of network · ${stats.pool.hashrate_gate?.display ?? "—"} gate · ${stats.pool.shares_10m} shares / 10m`
              : "Submit shares to estimate pool hashrate"}
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

      <section className={`block-proof ${latestBlock ? "found" : "waiting"}`}>
        <div className="block-proof-main">
          <span className="eyebrow">Pool block record</span>
          {latestBlock ? (
            <>
              <h2>Block #{latestBlock.height.toLocaleString()} found by this pool</h2>
              <p>
                Accepted into pool accounting {timeAgo(latestBlock.created_at)}.
                The hash below is the unique proof of this pool's block submission.
              </p>
              <code className="block-hash">
                {latestBlock.hash || "Hash pending node confirmation"}
              </code>
            </>
          ) : (
            <>
              <h2>No pool block found yet</h2>
              <p>
                Valid shares are being counted, but none has met the network block
                target. This card will show the accepted hash and finder immediately
                after a hit.
              </p>
            </>
          )}
        </div>
        <div className="block-proof-stats">
          <div>
            <span>Total found</span>
            <strong>{blocksFound}</strong>
          </div>
          <div>
            <span>Status</span>
            <strong className={latestBlock?.status === "orphaned" ? "danger" : latestBlock ? "success" : ""}>
              {latestBlock ? latestBlock.status : "Waiting"}
            </strong>
          </div>
          <div>
            <span>Confirmations</span>
            <strong>{latestBlock ? latestBlock.confirmations : "—"}</strong>
          </div>
          <div>
            <span>Reward</span>
            <strong>{latestBlock ? `${formatBtx(latestBlock.reward_sats)} BTX` : "—"}</strong>
          </div>
        </div>
      </section>

      {blockProgress && (
        <section className="luck-card">
          <div className="luck-head">
            <div>
              <h2>Block find probability</h2>
              <p className="luck-sub">{blockProgress.luck_message}</p>
            </div>
            <div className="luck-pct">
              <span className="luck-value">{blockProgress.progress_display}</span>
              <span className="luck-label">chance this round</span>
            </div>
          </div>
          <div className="luck-bar-track">
            <div
              className={`luck-bar-fill ${blockProgress.luck_status}`}
              style={{ width: `${Math.max(blockProgress.bar_fill_percent, blockProgress.progress_percent > 0 ? 2 : 0)}%` }}
            />
          </div>
          <div className="luck-meta">
            <span>Round: {blockProgress.round_elapsed.display}</span>
            <span>Mean wait now: {blockProgress.expected_block_time.display}</span>
            <span>50% within: {blockProgress.median_block_time.display}</span>
            <span>95% within: {blockProgress.p95_block_time.display}</span>
            <span>{blockProgress.round_shares.toLocaleString()} shares this round</span>
          </div>
          {blockProgress.last_block_luck_percent != null && (
            <p className="luck-note">
              Last pool block luck: {blockProgress.last_block_luck_percent.toFixed(1)}%
              {blockProgress.last_block_luck_percent < 100
                ? " (lucky — faster than expected)"
                : " (slower than expected)"}
            </p>
          )}
        </section>
      )}

      {mining && (
        <section className="mining-work">
          <div className="mining-work-head">
            <div>
              <h2>Block work (live from btxd)</h2>
              <p className="mining-work-lead">{mining.message}</p>
            </div>
            <div className="mining-work-badges">
              <span className={`chip ${mining.synced ? "accent" : ""}`}>
                {mining.synced ? "Node synced" : "Node syncing"}
              </span>
              {mining.can_find_blocks && (
                <span className="chip success">Blocks findable</span>
              )}
            </div>
          </div>

          {mining.active ? (
            <div className="mining-work-grid">
              <div className="mining-panel highlight">
                <h3>Mining block #{mining.mining_height?.toLocaleString()}</h3>
                <div className="metric-list">
                  <MetricRow
                    label="Chain tip"
                    value={
                      mining.chain_tip_height != null
                        ? `#${mining.chain_tip_height.toLocaleString()}`
                        : "—"
                    }
                  />
                  <MetricRow label="Job" value={mining.job_id ?? "—"} mono />
                  <MetricRow
                    label="Parent hash"
                    value={truncateHex(mining.prev_hash ?? "")}
                    mono
                  />
                  <MetricRow
                    label="Merkle root"
                    value={truncateHex(mining.merkle_root ?? "")}
                    mono
                  />
                  <MetricRow
                    label="Bits"
                    value={mining.bits ? `0x${mining.bits}` : "—"}
                    mono
                  />
                  <MetricRow label="btxd RPC" value={mining.rpc_source || "—"} mono />
                </div>
              </div>

              <div className="mining-panel">
                <h3>Targets (digest must be ≤)</h3>
                <div className="target-compare">
                  <div className="target-row">
                    <div className="target-label">
                      <span>Pool share</span>
                      <code>{truncateHex(mining.share_target ?? "", 12, 6)}</code>
                    </div>
                    <div className="target-track">
                      <div
                        className="target-fill share-fill"
                        style={{ width: `${targetBarWidth(targetLog10, targetLog10)}%` }}
                      />
                    </div>
                    <span className="target-note">vardiff — shares accepted here</span>
                  </div>
                  <div className="target-row">
                    <div className="target-label">
                      <span>Network block</span>
                      <code>{truncateHex(mining.block_target ?? "", 12, 6)}</code>
                    </div>
                    <div className="target-track">
                      <div
                        className="target-fill block-fill"
                        style={{ width: `${targetBarWidth(0, targetLog10)}%` }}
                      />
                    </div>
                    <span className="target-note">
                      ~{mining.share_easier?.display ?? "—"} harder — wins on-chain block
                    </span>
                  </div>
                </div>
                <p className="mining-explainer">
                  Same MatMul digest for every nonce. Miners already compute it; when{" "}
                  <code>digest ≤ block target</code>, the pool calls <code>submitblock</code> on
                  your node. Shares are partial proofs at an easier target.
                </p>
              </div>

              <div className="mining-panel">
                <h3>Find odds (this pool)</h3>
                <div className="metric-list">
                  <MetricRow
                    label="Est. pool block"
                    value={mining.est_pool_block_time?.display ?? "—"}
                  />
                  <MetricRow
                    label="Network block"
                    value={mining.network_block_time?.display ?? "—"}
                  />
                  <MetricRow
                    label="MatMul seeds"
                    value={`a=${truncateHex(mining.seed_a ?? "", 8, 4)} b=${truncateHex(mining.seed_b ?? "", 8, 4)}`}
                    mono
                  />
                  <MetricRow
                    label="ε bits"
                    value={String(mining.epsilon_bits ?? 18)}
                  />
                </div>
                <p className="mining-explainer muted">
                  One RX 7800 XT (~200 H/s) cannot outpace the network alone, but it{" "}
                  <strong>can</strong> find a block — same as solo mining, just much less
                  frequent. More pool hashrate improves the odds proportionally.
                </p>
              </div>
            </div>
          ) : (
            <p className="empty">{mining.message}</p>
          )}
        </section>
      )}

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
        <StatCard label="Pool hashrate (10m)" value={stats?.pool.hashrate_10m.display ?? "0 N/s"} />
        <StatCard label="Network share" value={`${stats?.pool.network_share_percent?.toFixed(3) ?? "0"}%`} accent />
        <StatCard label="Pool gate rate (10m)" value={stats?.pool.hashrate_gate_10m?.display ?? stats?.pool.hashrate_gate?.display ?? "0 N/s"} />
        <StatCard label="Miner-reported N/s" value={stats?.pool.reported_nonce_rate?.display ?? "0 N/s"} />
        <StatCard label="Total work" value={(pool?.totals.total_work ?? 0).toFixed(2)} />
        <StatCard label="Next difficulty" value={stats?.network.next_difficulty?.toFixed(6) ?? "—"} />
        <StatCard label="Chain" value={stats?.network.chain ?? "main"} />
      </section>

      <section className="connect-card" id="connect">
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
        <p className="payment-note">
          {pool?.payment_mode?.toUpperCase() ?? "PPLNS"} payouts every{" "}
          {pool?.payout_interval_hours ?? 24}h · min {pool?.min_payout_btx ?? 5} BTX · fee{" "}
          {pool?.fee_percent ?? 1}%
        </p>
        <p className="payment-note payout-safeguards">
          New-chain safeguards: {pool?.coinbase_maturity ?? 200} confirmations,{" "}
          {pool?.payout_max_address_btx ?? 25} BTX max per address,{" "}
          {pool?.payout_daily_limit_btx ?? 100} BTX daily pool limit, and{" "}
          {pool?.payout_wallet_reserve_btx ?? 1} BTX wallet reserve.
        </p>
        <form
          className="wallet-lookup"
          onSubmit={(e) => {
            e.preventDefault();
            const addr = lookupAddress.trim();
            if (addr.startsWith("btx1")) {
              window.location.href = `/wallet/${encodeURIComponent(addr)}`;
            }
          }}
        >
          <input
            type="text"
            placeholder="btx1z... check your balance"
            value={lookupAddress}
            onChange={(e) => setLookupAddress(e.target.value)}
          />
          <button type="submit">View wallet</button>
        </form>
        <pre className="miner-config">{`# amdbtx (~/.amdbtx-miner/config.yaml)
mining_mode: "pool"
pool_host: "${host}"
pool_port: ${pool?.stratum_port ?? 3333}
payout_address: "btx1z...YOUR_ADDRESS"
worker_name: "rig-1"

# btx-nvidia-miner
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
                  <th>Pool N/s</th>
                  <th>Miner N/s</th>
                  <th>Last seen</th>
                </tr>
              </thead>
              <tbody>
                {miners.map((m) => (
                  <tr key={m.canonical_name || m.address}>
                    <td className="mono">{truncate(m.canonical_name || m.address, 8)}</td>
                    <td>{m.shares_valid}</td>
                    <td className={m.shares_invalid > 0 ? "danger" : ""}>{m.shares_invalid}</td>
                    <td className="muted">
                      {m.hashrate?.display ?? "—"}
                    </td>
                    <td className="muted">
                      {m.hashrate_nonce_reported?.display ?? "—"}
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
                  <th>Block?</th>
                  <th>When</th>
                </tr>
              </thead>
              <tbody>
                {shares.map((s, i) => (
                  <tr key={i} className={s.is_block ? "block-row" : ""}>
                    <td className="mono">{truncate(s.address, 6)}</td>
                    <td className="mono muted">{s.job_id.slice(0, 18)}...</td>
                    <td>{s.difficulty.toFixed(4)}</td>
                    <td className={s.is_block ? "success" : "muted"}>
                      {s.is_block ? "BLOCK" : "share"}
                    </td>
                    <td className="muted">{timeAgo(s.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Panel>
      </div>

      <section className="blocks-history">
        <Panel title="Pool block history">
          {blocks.length === 0 ? (
            <EmptyState text="No blocks found by this pool yet" />
          ) : (
            <table>
              <thead>
                <tr>
                  <th>Height</th>
                  <th>Block hash</th>
                  <th>Finder</th>
                  <th>Reward</th>
                  <th>Status</th>
                  <th>Confs</th>
                  <th>When</th>
                </tr>
              </thead>
              <tbody>
                {blocks.map((b, i) => (
                  <tr key={i}>
                    <td>{b.height}</td>
                    <td className="mono">{truncateHex(b.hash, 10, 8)}</td>
                    <td className="mono">{truncate(b.finder_address, 8)}</td>
                    <td className="success">{formatBtx(b.reward_sats)} BTX</td>
                    <td className={b.status === "orphaned" ? "danger" : "success"}>
                      {b.status}
                    </td>
                    <td>{b.confirmations}</td>
                    <td className="muted">{timeAgo(b.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Panel>
      </section>

      <footer className="footer">
        <span>
          Pool address: <code>{pool?.address ? truncate(pool.address, 10) : "—"}</code>
        </span>
        <span>
          {pool?.payment_mode?.toUpperCase() ?? "PPLNS"} · Fee {pool?.fee_percent ?? 0}% · Payouts every{" "}
          {pool?.payout_interval_hours ?? 24}h
        </span>
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

function OperationalCard({
  label,
  value,
  note,
  tone,
}: {
  label: string;
  value: string;
  note: string;
  tone: "good" | "warn" | "neutral";
}) {
  return (
    <div className={`operational-card ${tone}`}>
      <span className="operational-label">{label}</span>
      <strong>{value}</strong>
      <span className="operational-note">{note}</span>
    </div>
  );
}
