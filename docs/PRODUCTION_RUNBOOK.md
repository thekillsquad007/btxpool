# Production Runbook

## Current safety state

- The live wallet is encrypted and automatic payouts are enabled.
- The wallet is currently unfunded, so no payout can be sent yet.
- Keep the payout caps, daily 00:00 UTC schedule, 200-confirmation maturity,
  wallet reserve, and chain guard enabled.
- Do not restart WSL while BTX snapshot background validation is active.
- Keep the BTX mining chain guard enabled.

## Service installation

The current host uses Windows Task Scheduler while WSL systemd is disabled.
Install or refresh the recurring start, health, peer, and backup tasks from an
elevated PowerShell prompt:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/install-windows-tasks.ps1
```

The start task is intentionally idempotent and runs every five minutes, so it
also recovers the node and pool after WSL or process failure.

WSL systemd must be enabled only during an approved maintenance window.
After snapshot validation completes:

```bash
bash scripts/install-systemd.sh
```

Verify:

```bash
systemctl status btxd btxpool
systemctl list-timers \
  btxpool-backup.timer \
  btxpool-wallet-backup.timer \
  btxpool-health.timer \
  btxpool-peers.timer
curl -fsS http://127.0.0.1:8080/api/health
curl -fsS http://127.0.0.1:8080/metrics
```

## Backups

The live ledger belongs on WSL ext4:

```text
/home/aravindthana/.local/share/btxpool/pool.db
```

Run an online backup manually:

```bash
bash scripts/backup-db.sh
```

Backups are integrity checked, kept under
`~/.local/share/btxpool/backups`, and retained for 14 days by default.
Copy encrypted backups to a second machine or object store.

Create and verify an encrypted wallet backup:

```bash
bash scripts/backup-wallet.sh
```

Wallet backups are kept under
`~/.local/share/btxpool/wallet-backups` for 30 days. The script requires
both protected passphrase files, verifies that the recovered PQ descriptors
contain their seed material, creates a native wallet backup and encrypted
bundle archive, and locks the wallet before returning. A pruned node may
report `scan_incomplete`; that warning does not replace the seed checks.

## Peer monitoring

Run the near-tip check manually:

```bash
bash scripts/ensure-peers.sh
```

The check requires at least three peers with usable sync heights and three
within two blocks of the local tip, matching the effective peer eligibility
observed from the node's chain guard.
When below that threshold it tries the official fallbacks plus recent IPv4
addresses from the node's own address database. It does not disable the
mining chain guard or select a competing chain.

Check assume-UTXO background validation progress:

```bash
bash scripts/snapshot-status.sh
```

The pool may serve the snapshot chain while the node independently validates
historical blocks up to the snapshot base height. Do not restart WSL until
that background validation completes.

## Public hostname

The public hostname is:

```text
btxfamilypool.duckdns.org
```

HTTPS is terminated by Caddy on the Windows host and proxied to the pool API
at `127.0.0.1:8080`. Caddy obtains and renews the public certificate through
the DuckDNS DNS challenge. The DuckDNS token is stored outside Git beside the
Caddy binary with user-only Windows ACLs. Run
`scripts/wsl-port-forward.ps1` from an elevated PowerShell prompt to create
the Windows TCP 80/443 firewall rule, and forward router TCP 443 to the
Windows host.

## Node release

The production node runs BTX 0.32.9. This release must be active before
height 130,000 because it introduces the empty-block subsidy consensus rule.
The previous 0.32.8 binaries remain beside the installed real binaries with
the `.v0.32.8` suffix for emergency rollback only.

This is direct DNS to the public IP, not a Cloudflare proxy. Cloudflare's
standard proxy can carry the HTTP dashboard on supported HTTP ports, but raw
Stratum TCP on port 3333 must use direct DNS or Cloudflare Spectrum.

## Payout activation

Before changing `payout_dry_run`:

1. Create and encrypt the node wallet.
2. Set `rpc_wallet` and confirm the pool coinbase address is controlled by it:

   ```bash
   bash scripts/check-wallet.sh
   ```

3. Back up the wallet and recovery material offline.
4. Test a small manual send and restoration procedure.
5. Reconcile any payout with status `reserved`, `sending`, or `uncertain`.
6. Run at least one complete dry-run maturity and payout cycle.

Current new-chain safety policy:

- 200 confirmations before miner credits become payable
- one payout cycle daily at 00:00 UTC
- 25 BTX maximum per address per cycle
- 100 BTX maximum across all payouts in a rolling 24-hour window
- 1 BTX retained in the hot wallet for fees and recovery
- automatic sends remain suspended by the node chain guard during peer or
  chain-consensus anomalies

## Incident response

- No job: inspect `/api/health`, node peers, header lag, and chain guard.
- High verifier queue: increase vardiff before adding verifier workers.
- Uncertain payout: stop automatic payouts and reconcile the wallet before
  releasing or finalizing the ledger entry.
- Database failure: stop the pool, restore the latest integrity-checked
  backup, then compare recent shares and payouts before reopening Stratum.
