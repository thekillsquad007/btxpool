# Production Runbook

## Current safety state

- The live wallet is encrypted and automatic payouts are enabled.
- The wallet is currently unfunded, so no payout can be sent yet.
- Keep the payout caps, 24-hour initial delay, 200-confirmation maturity,
  wallet reserve, and chain guard enabled.
- Do not restart WSL while BTX snapshot background validation is active.
- Keep the BTX mining chain guard enabled.

## Service installation

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

When no connected peer is within six blocks of the local tip, the check asks
the node to reconnect to the official BTX fallback peers. It does not disable
the mining chain guard or select a competing chain.

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
- 24-hour delay after pool startup before the first payout cycle
- 24 hours between payout cycles
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
