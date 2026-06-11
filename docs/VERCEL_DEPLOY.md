# Deploy dashboard on Vercel

The **mining pool backend cannot run on Vercel** (Stratum TCP :3333, SQLite, long-running workers). Vercel hosts only the **dashboard UI** on your custom domain.

## Architecture

```
Miners ──Stratum :3333──► Your PC / VPS (btxpool + btxd)
                              │
                              ├── API :8080 ◄── tunnel / port forward
                              │
Vercel (pool.yourdomain.com) ─┘ proxy /api or VITE_POOL_API_URL
```

| Component | Where it runs |
|-----------|----------------|
| Stratum :3333 | Home PC, VPS, or WSL with public IP / tunnel |
| Pool API :8080 | Same machine as Stratum |
| btxd + wallet | `~/.bitcoin` on pool machine |
| Dashboard | Vercel (custom domain) |

## 1. Expose pool API to the internet

Pick one:

- **Cloudflare Tunnel** — free HTTPS URL to `localhost:8080`
- **Netbird / Tailscale** — share with miners who join your mesh
- **Router port forward** — forward 3333 (stratum) and 8080 (API); use HTTPS via reverse proxy if possible

Miners always need **Stratum reachable** at your public IP or hostname on port **3333**.

## 2. Vercel project setup

1. Import repo [thekillsquad007/btxpool](https://github.com/thekillsquad007/btxpool)
2. **Root Directory:** `frontend`
3. **Framework:** Vite
4. **Build command:** `npm run build` (default)
5. **Output:** `dist`

### Environment variables (Vercel dashboard)

| Variable | Example | Purpose |
|----------|---------|---------|
| `POOL_API_ORIGIN` | `https://pool-api.your-tunnel.trycloudflare.com` | Proxies `/api/*` on your Vercel domain to the pool server (recommended) |
| `VITE_POOL_API_URL` | same URL | Alternative: browser calls API directly (needs CORS; pool already allows `*`) |

Use **one** of the above. `POOL_API_ORIGIN` keeps a single domain and avoids CORS.

## 3. Custom domain

In Vercel → Project → Domains → add `pool.yourdomain.com`.

Miners connect to Stratum separately, e.g. `stratum+tcp://pool.yourdomain.com:3333` only works if you also expose :3333 on that host (usually your home IP, not Vercel).

Typical setup:

- Dashboard: `https://pool.yourdomain.com` (Vercel)
- Stratum: `stratum+tcp://YOUR_HOME_IP:3333` or `stratum+tcp://stratum.yourdomain.com:3333` (DNS A record → home IP)

## 4. Local node (`~/.bitcoin`)

BTX uses `~/.bitcoin` as the default data directory. Ensure `~/.bitcoin/btx.conf` has:

```ini
server=1
rpcuser=miner
rpcpassword=miner
rpcallowip=127.0.0.1
rpcbind=127.0.0.1
txindex=1
```

Pool `config.yaml`:

```yaml
rpc_url: "http://127.0.0.1:19334"
rpc_user: "miner"
rpc_password: "miner"
```

Start synced node:

```bash
btxd -datadir=$HOME/.bitcoin -daemon
btx-cli -datadir=$HOME/.bitcoin getblockchaininfo
```

## 5. Deploy

```bash
cd frontend
npm run build
# or push to GitHub — Vercel auto-deploys
```

Verify: open `https://pool.yourdomain.com` — pool stats should load if `POOL_API_ORIGIN` is set correctly.