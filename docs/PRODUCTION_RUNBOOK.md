# Production Runbook

## Current safety state

- Keep `payout_dry_run: true` until the node wallet is created, backed up,
  funded, and tested.
- Do not restart WSL while BTX snapshot background validation is active.
- Keep the BTX mining chain guard enabled.

## Service installation

WSL systemd must be enabled only during an approved maintenance window.
After snapshot validation completes:

```bash
sudo cp deploy/systemd/*.service deploy/systemd/*.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now btxd btxpool btxpool-backup.timer btxpool-health.timer
```

Verify:

```bash
systemctl status btxd btxpool
systemctl list-timers btxpool-backup.timer btxpool-health.timer
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

## Incident response

- No job: inspect `/api/health`, node peers, header lag, and chain guard.
- High verifier queue: increase vardiff before adding verifier workers.
- Uncertain payout: stop automatic payouts and reconcile the wallet before
  releasing or finalizing the ledger entry.
- Database failure: stop the pool, restore the latest integrity-checked
  backup, then compare recent shares and payouts before reopening Stratum.
