# Web Dashboard — Setup & Usage

The bot includes a password-protected web dashboard built with Flask.

---

## Setting the Dashboard Password

1. Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```

2. Edit `.env` and set a strong password:
   ```
   DASHBOARD_PASSWORD=my-secret-password-here
   ```

3. **Never commit `.env` to version control.**

---

## Running the Dashboard

### Option A: Alongside the bot (automatic)

When you run the bot with `python main.py`, the dashboard starts automatically in the background (if `dashboard.enabled: true` in `config.yaml`).

The dashboard URL will be printed:
```
[dashboard] Web dashboard running at http://0.0.0.0:8050
```

### Option B: Standalone (for development or debugging)

```bash
python dashboard.py
```

This starts only the dashboard on port 8050 (or whatever is in `config.yaml`).

---

## Dashboard Pages

### Overview (`/`)
- Bot status (running / paused / stopped / cooldown)
- Total realized PnL and today's PnL
- Win rate, trade counts
- Equity curve chart

### Positions (`/positions`)
- Table of all open positions with market, timeframe, direction, entry price, size
- **Graceful Stop** button — requests the bot to stop after the current window

### History (`/history`)
- Full trade log with timestamp, market, direction, PnL, result
- Summary statistics: win rate, avg win, avg loss

---

## Changing the Port

Edit `config.yaml`:
```yaml
dashboard:
  port: 8050     # change to any available port
  host: "0.0.0.0"
```

Or use `127.0.0.1` instead of `0.0.0.0` to only allow local connections.

---

## Exposing on a VPS

If running on a remote server:

1. **Simple approach — direct access:**
   - Set `host: "0.0.0.0"` in config.yaml
   - Open port 8050 in your firewall
   - Access at `http://your-server-ip:8050`

2. **Recommended — reverse proxy with nginx:**
   ```nginx
   server {
       listen 80;
       server_name bot.yourdomain.com;

       location / {
           proxy_pass http://127.0.0.1:8050;
           proxy_set_header Host $host;
           proxy_set_header X-Real-IP $remote_addr;
       }
   }
   ```
   Then add HTTPS with Let's Encrypt: `sudo certbot --nginx`

3. **SSH tunnel (quick and secure):**
   ```bash
   ssh -L 8050:localhost:8050 user@your-server
   ```
   Then open `http://localhost:8050` on your local machine.
