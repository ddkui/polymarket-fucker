"""
dashboard.py – Password-Protected Web Dashboard (Flask)
=======================================================
Three pages:
  /            → Overview (status, PnL, equity chart)
  /positions   → Open positions table + graceful stop
  /history     → Trade history with stats

Password is read from DASHBOARD_PASSWORD in .env.
"""

import os
import json
from functools import wraps
from datetime import datetime, timezone

from flask import (
    Flask, render_template_string, request, redirect,
    url_for, session, flash, jsonify,
)
from logging_utils import TradeDB


# ========================================================================
#  HTML Templates  (embedded for single-file simplicity)
# ========================================================================

BASE_TEMPLATE = """
<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{{ title }} — BTC Polymarket Bot</title>
  <style>
    :root {
      --bg:       #0f1117;
      --surface:  #1a1d28;
      --card:     #21253a;
      --border:   #2d3250;
      --text:     #e2e4ea;
      --muted:    #8b8fa3;
      --accent:   #6c5ce7;
      --green:    #00b894;
      --red:      #e74c3c;
      --yellow:   #ffc048;
      --blue:     #0984e3;
      --gradient: linear-gradient(135deg, #6c5ce7 0%, #0984e3 100%);
      --font:     'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    }
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

    * { box-sizing: border-box; margin: 0; padding: 0; }

    body {
      font-family: var(--font);
      background: var(--bg);
      color: var(--text);
      min-height: 100vh;
    }

    /* ---- Nav ---- */
    nav {
      background: var(--surface);
      border-bottom: 1px solid var(--border);
      padding: 0.75rem 2rem;
      display: flex;
      align-items: center;
      gap: 2rem;
      position: sticky;
      top: 0;
      z-index: 100;
      backdrop-filter: blur(12px);
    }
    nav .logo {
      font-weight: 700;
      font-size: 1.1rem;
      background: var(--gradient);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
    }
    nav a {
      color: var(--muted);
      text-decoration: none;
      font-weight: 500;
      font-size: 0.9rem;
      padding: 0.4rem 0.8rem;
      border-radius: 6px;
      transition: all 0.2s;
    }
    nav a:hover, nav a.active {
      color: var(--text);
      background: rgba(108, 92, 231, 0.15);
    }
    nav .spacer { flex: 1; }
    nav .logout {
      color: var(--muted);
      font-size: 0.85rem;
    }

    /* ---- Layout ---- */
    .container { max-width: 1200px; margin: 0 auto; padding: 2rem; }

    /* ---- Cards ---- */
    .card-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
      gap: 1rem;
      margin-bottom: 2rem;
    }
    .card {
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 1.2rem 1.4rem;
      transition: transform 0.15s;
    }
    .card:hover { transform: translateY(-2px); }
    .card .label { font-size: 0.8rem; color: var(--muted); margin-bottom: 0.3rem; text-transform: uppercase; letter-spacing: 0.05em; }
    .card .value { font-size: 1.6rem; font-weight: 700; }
    .card .value.green { color: var(--green); }
    .card .value.red   { color: var(--red); }
    .card .value.yellow { color: var(--yellow); }

    /* ---- Tables ---- */
    table {
      width: 100%;
      border-collapse: separate;
      border-spacing: 0;
      background: var(--card);
      border-radius: 12px;
      overflow: hidden;
      margin-bottom: 2rem;
    }
    th {
      background: var(--surface);
      color: var(--muted);
      font-weight: 600;
      font-size: 0.8rem;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      padding: 0.8rem 1rem;
      text-align: left;
    }
    td {
      padding: 0.7rem 1rem;
      border-top: 1px solid var(--border);
      font-size: 0.9rem;
    }
    tr:hover td { background: rgba(108, 92, 231, 0.05); }
    .badge {
      display: inline-block;
      padding: 0.15rem 0.6rem;
      border-radius: 999px;
      font-size: 0.75rem;
      font-weight: 600;
    }
    .badge.win  { background: rgba(0, 184, 148, 0.15); color: var(--green); }
    .badge.loss { background: rgba(231, 76, 60, 0.15);  color: var(--red); }
    .badge.open { background: rgba(9, 132, 227, 0.15);  color: var(--blue); }
    .badge.up   { color: var(--green); }
    .badge.down { color: var(--red); }

    /* ---- Chart placeholder ---- */
    .chart-container {
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 1.5rem;
      margin-bottom: 2rem;
      min-height: 250px;
    }
    .chart-container h3 { margin-bottom: 1rem; font-size: 1rem; }
    .chart-svg { width: 100%; height: 200px; }

    /* ---- Logs placeholder ---- */
    .logs-container {
      background: #0f1117;
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 1.5rem;
      margin-bottom: 2rem;
      max-height: 300px;
      overflow-y: auto;
      font-family: 'Courier New', Courier, monospace;
      font-size: 0.85rem;
      white-space: pre-wrap;
    }
    .logs-container h3 { 
      margin-bottom: 1rem; 
      font-size: 1rem; 
      font-family: var(--font); 
      position: sticky;
      top: 0;
      background: #0f1117;
      padding-bottom: 0.5rem;
      border-bottom: 1px solid var(--border);
    }

    /* ---- Status badges ---- */
    .status-running  { color: var(--green); }
    .status-paused   { color: var(--yellow); }
    .status-stopped  { color: var(--red); }
    .status-cooldown { color: var(--yellow); }

    /* ---- Button ---- */
    .btn {
      display: inline-block;
      padding: 0.5rem 1.2rem;
      border: none;
      border-radius: 8px;
      font-family: var(--font);
      font-weight: 600;
      font-size: 0.85rem;
      cursor: pointer;
      transition: all 0.2s;
    }
    .btn-primary {
      background: var(--gradient);
      color: white;
    }
    .btn-danger {
      background: rgba(231, 76, 60, 0.15);
      color: var(--red);
      border: 1px solid var(--red);
    }
    .btn:hover { opacity: 0.85; transform: translateY(-1px); }

    /* ---- Login page ---- */
    .login-wrapper {
      min-height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
      background: var(--bg);
    }
    .login-box {
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 16px;
      padding: 2.5rem;
      width: 380px;
      text-align: center;
    }
    .login-box h1 {
      background: var(--gradient);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
      margin-bottom: 0.5rem;
    }
    .login-box p { color: var(--muted); margin-bottom: 1.5rem; font-size: 0.9rem; }
    .login-box input[type="password"] {
      width: 100%;
      padding: 0.7rem 1rem;
      border: 1px solid var(--border);
      border-radius: 8px;
      background: var(--surface);
      color: var(--text);
      font-family: var(--font);
      font-size: 0.95rem;
      margin-bottom: 1rem;
      outline: none;
    }
    .login-box input:focus { border-color: var(--accent); }
    .login-box .btn { width: 100%; padding: 0.7rem; font-size: 1rem; }
    .flash-error { color: var(--red); font-size: 0.85rem; margin-bottom: 1rem; }

    /* ---- Section title ---- */
    h2 { font-size: 1.3rem; margin-bottom: 1rem; }

    /* ---- Responsive ---- */
    @media (max-width: 768px) {
      .container { padding: 1rem; }
      .card-grid { grid-template-columns: 1fr 1fr; }
    }
  </style>
</head>
<body>
  {% if session.get('authenticated') %}
  <nav>
    <span class="logo">₿ BTC Bot</span>
    <a href="/" class="{{ 'active' if page == 'overview' }}">Overview</a>
    <a href="/positions" class="{{ 'active' if page == 'positions' }}">Positions</a>
    <a href="/history" class="{{ 'active' if page == 'history' }}">History</a>
    <span class="spacer"></span>
    <a href="/logout" class="logout">Logout ↗</a>
  </nav>
  {% endif %}
  {% block content %}{% endblock %}
</body>
</html>
"""

LOGIN_PAGE = """
{% extends "base" %}
{% block content %}
<div class="login-wrapper">
  <div class="login-box">
    <h1>₿ BTC Bot</h1>
    <p>Enter dashboard password to continue</p>
    {% for msg in get_flashed_messages() %}
      <div class="flash-error">{{ msg }}</div>
    {% endfor %}
    <form method="POST">
      <input type="password" name="password" placeholder="Password" autofocus>
      <button class="btn btn-primary" type="submit">Log In</button>
    </form>
  </div>
</div>
{% endblock %}
"""

OVERVIEW_PAGE = """
{% extends "base" %}
{% block content %}
<div class="container">
  <h2>Dashboard Overview</h2>

  <div class="card-grid">
    <div class="card">
      <div class="label">Bot Status</div>
      <div class="value status-{{ status }}">{{ status | upper }}</div>
    </div>
    <div class="card">
      <div class="label">Total PnL</div>
      <div class="value {{ 'green' if stats.total_pnl >= 0 else 'red' }}">
        ${{ "%.2f"|format(stats.total_pnl) }}
      </div>
    </div>
    <div class="card">
      <div class="label">Today's PnL</div>
      <div class="value {{ 'green' if stats.today_pnl >= 0 else 'red' }}">
        ${{ "%.2f"|format(stats.today_pnl) }}
      </div>
    </div>
    <div class="card">
      <div class="label">Win Rate</div>
      <div class="value">{{ stats.win_rate }}%</div>
    </div>
    <div class="card">
      <div class="label">Trades Today</div>
      <div class="value">{{ stats.today_trades }}</div>
    </div>
    <div class="card">
      <div class="label">Total Trades</div>
      <div class="value">{{ stats.total_trades }}</div>
    </div>
    <div class="card">
      <div class="label">Open Positions</div>
      <div class="value yellow">{{ stats.open_positions }}</div>
    </div>
    <div class="card">
      <div class="label">Avg Win / Loss</div>
      <div class="value" style="font-size:1rem;">
        <span class="green">${{ "%.2f"|format(stats.avg_win) }}</span> /
        <span class="red">${{ "%.2f"|format(stats.avg_loss) }}</span>
      </div>
    </div>
    <div class="card" style="background: var(--surface); border-color: var(--accent);">
      <div class="label">Current BTC Price</div>
      <div class="value yellow">
        ${{ "{:,.2f}".format(status_detail.state.btc_price or 0) }}
      </div>
      <div class="label" style="margin-top:0.2rem; font-size:0.7rem;">Source: {{ status_detail.state.btc_source or '—' }}</div>
    </div>
  </div>

  <!-- Active Markets Countdown -->
  <div style="margin-bottom: 2rem;">
    <h3>⏱️ Active Market Monitoring</h3>
    <div style="display: flex; gap: 1rem; flex-wrap: wrap; margin-top: 1rem;">
      {% if status_detail.state.markets %}
        {% for m in status_detail.state.markets %}
          <div class="card" style="flex: 1; min-width: 250px; border-left: 4px solid var(--accent);">
            <div class="label">{{ m.slug }}</div>
            <div class="value" style="font-size: 1.2rem;">
              <span style="color: var(--muted)">Ends in:</span> 
              <span class="{{ 'red' if m.seconds_left < 60 else 'yellow' if m.seconds_left < 300 else 'green' }}">
                {{ m.seconds_left // 60 }}m {{ m.seconds_left % 60 }}s
              </span>
            </div>
            <div style="display: flex; justify-content: space-between; margin-top: 0.5rem; font-size: 0.8rem;">
              <span>UP: ${{ "%.2f"|format(m.up_price) }}</span>
              <span>DOWN: ${{ "%.2f"|format(m.down_price) }}</span>
            </div>
          </div>
        {% endfor %}
      {% else %}
        <p style="color: var(--muted);">Scanning for active markets...</p>
      {% endif %}
    </div>
  </div>

  <!-- Equity Curve -->
  <div class="chart-container">
    <h3>📈 Equity Curve</h3>
    {% if equity_data %}
    <svg class="chart-svg" viewBox="0 0 800 200" preserveAspectRatio="none">
      <polyline fill="none" stroke="#6c5ce7" stroke-width="2"
                points="{{ equity_points }}" />
      <polyline fill="url(#grad)" stroke="none"
                points="{{ equity_fill }}" />
      <defs>
        <linearGradient id="grad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="#6c5ce7" stop-opacity="0.3"/>
          <stop offset="100%" stop-color="#6c5ce7" stop-opacity="0"/>
        </linearGradient>
      </defs>
    </svg>
    {% else %}
    <p style="color: var(--muted); text-align: center; padding-top: 80px;">
      No equity data yet — trades will appear here.
    </p>
    {% endif %}
  </div>

  <!-- Recent Logs -->
  <div class="logs-container">
    <h3>📝 Live Bot Activity (Recent Logs)</h3>
    {% if logs %}
      {% for line in logs %}
        <div style="color: {{ 'var(--red)' if 'ERROR' in line else 'var(--yellow)' if 'WARNING' in line else 'var(--green)' if 'WIN' in line or 'SUCCESS' in line else 'var(--muted)' }}">{{ line }}</div>
      {% endfor %}
    {% else %}
      <p style="color: var(--muted);">No logs available yet.</p>
    {% endif %}
  </div>
</div>

<script>
  // Auto-refresh the overview page every 5 seconds to show live logs and updates
  setTimeout(function() {
    window.location.reload();
  }, 5000);
</script>
{% endblock %}
"""

POSITIONS_PAGE = """
{% extends "base" %}
{% block content %}
<div class="container">
  <h2>Open Positions</h2>

  {% if positions %}
  <table>
    <thead>
      <tr>
        <th>Market</th>
        <th>TF</th>
        <th>Direction</th>
        <th>Entry Price</th>
        <th>Size ($)</th>
        <th>Strategy</th>
        <th>Regime</th>
        <th>Opened</th>
      </tr>
    </thead>
    <tbody>
      {% for p in positions %}
      <tr>
        <td>{{ p.market }}</td>
        <td>{{ p.timeframe }}m</td>
        <td><span class="badge {{ p.direction }}">{{ p.direction | upper }}</span></td>
        <td>{{ "%.4f"|format(p.entry_price) }}</td>
        <td>${{ "%.2f"|format(p.size_usd) }}</td>
        <td>{{ p.strategy_tag or '—' }}</td>
        <td>{{ p.regime or '—' }}</td>
        <td>{{ p.timestamp[:19] }}</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
  {% else %}
  <div class="card" style="text-align:center; padding:3rem;">
    <p style="color: var(--muted);">No open positions right now.</p>
  </div>
  {% endif %}

  <div style="margin-top:1rem;">
    <form method="POST" action="/graceful-stop">
      <button class="btn btn-danger" type="submit"
              onclick="return confirm('Request graceful stop after current window?')">
        ⏹ Request Graceful Stop
      </button>
    </form>
  </div>
</div>
{% endblock %}
"""

HISTORY_PAGE = """
{% extends "base" %}
{% block content %}
<div class="container">
  <h2>Trade History</h2>

  <!-- Summary Stats -->
  <div class="card-grid">
    <div class="card">
      <div class="label">Win Rate (All)</div>
      <div class="value">{{ stats.win_rate }}%</div>
    </div>
    <div class="card">
      <div class="label">Avg Win</div>
      <div class="value green">${{ "%.2f"|format(stats.avg_win) }}</div>
    </div>
    <div class="card">
      <div class="label">Avg Loss</div>
      <div class="value red">${{ "%.2f"|format(stats.avg_loss) }}</div>
    </div>
    <div class="card">
      <div class="label">Total PnL</div>
      <div class="value {{ 'green' if stats.total_pnl >= 0 else 'red' }}">
        ${{ "%.2f"|format(stats.total_pnl) }}
      </div>
    </div>
  </div>

  {% if trades %}
  <table>
    <thead>
      <tr>
        <th>Time</th>
        <th>Market</th>
        <th>TF</th>
        <th>Dir</th>
        <th>Entry</th>
        <th>Size ($)</th>
        <th>PnL</th>
        <th>Result</th>
        <th>Tag</th>
        <th>Regime</th>
      </tr>
    </thead>
    <tbody>
      {% for t in trades %}
      <tr>
        <td>{{ t.timestamp[:19] }}</td>
        <td title="{{ t.market }}">{{ t.market[:30] }}</td>
        <td>{{ t.timeframe }}m</td>
        <td><span class="badge {{ t.direction }}">{{ t.direction | upper }}</span></td>
        <td>{{ "%.4f"|format(t.entry_price) }}</td>
        <td>${{ "%.2f"|format(t.size_usd) }}</td>
        <td class="{{ 'green' if (t.pnl or 0) >= 0 else 'red' }}">
          ${{ "%.2f"|format(t.pnl or 0) }}
        </td>
        <td>
          {% if t.result == 'win' %}
            <span class="badge win">WIN</span>
          {% elif t.result == 'loss' %}
            <span class="badge loss">LOSS</span>
          {% else %}
            <span class="badge open">OPEN</span>
          {% endif %}
        </td>
        <td>{{ t.strategy_tag or '—' }}</td>
        <td>{{ t.regime or '—' }}</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
  {% else %}
  <div class="card" style="text-align:center; padding:3rem;">
    <p style="color: var(--muted);">No trades recorded yet.</p>
  </div>
  {% endif %}
</div>
{% endblock %}
"""


# ========================================================================
#  Flask App Factory
# ========================================================================

def create_app(config: dict = None) -> Flask:
    """Create and configure the Flask dashboard app."""
    app = Flask(__name__)
    app.secret_key = os.urandom(32)

    # Dashboard password from env
    dash_password = os.getenv("DASHBOARD_PASSWORD", "admin")

    # Trade DB path from config
    db_path = "data/trades.db"
    if config:
        db_path = config.get("logging", {}).get("db_file", db_path)

    db = TradeDB(db_path)

    # ---- Template rendering helper -----------------------------------
    # We use render_template_string with Jinja2 {% extends %} via
    # a custom template loader trick.

    from jinja2 import DictLoader, Environment

    templates = {
        "base": BASE_TEMPLATE,
        "login": LOGIN_PAGE,
        "overview": OVERVIEW_PAGE,
        "positions": POSITIONS_PAGE,
        "history": HISTORY_PAGE,
    }

    jinja_env = Environment(loader=DictLoader(templates))

    def render(template_name, **kwargs):
        tpl = jinja_env.get_template(template_name)
        # Pass Flask's session and flashed messages
        kwargs["session"] = session
        kwargs["get_flashed_messages"] = lambda: flask_msgs
        return tpl.render(**kwargs)

    # ---- Auth decorator ----------------------------------------------

    def login_required(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if not session.get("authenticated"):
                return redirect(url_for("login"))
            return f(*args, **kwargs)
        return decorated

    # ---- Routes ------------------------------------------------------

    @app.route("/login", methods=["GET", "POST"])
    def login():
        nonlocal flask_msgs
        flask_msgs = []
        if request.method == "POST":
            if request.form.get("password") == dash_password:
                session["authenticated"] = True
                return redirect("/")
            else:
                flask_msgs = ["Invalid password"]
        return render("login", title="Login", page="login")

    @app.route("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    @app.route("/")
    @login_required
    def overview():
        stats = db.get_stats()
        status_detail = db.get_status_detail()
        equity_data = db.get_equity_history(limit=200)

        # Build SVG points for equity curve
        equity_points = ""
        equity_fill = ""
        if equity_data:
            n = len(equity_data)
            equities = [e["equity"] for e in equity_data]
            min_eq = min(equities) if equities else 0
            max_eq = max(equities) if equities else 1
            range_eq = max(max_eq - min_eq, 0.01)

            points = []
            for i, e in enumerate(equities):
                x = (i / max(n - 1, 1)) * 800
                y = 200 - ((e - min_eq) / range_eq) * 180 - 10
                points.append(f"{x:.0f},{y:.0f}")

            equity_points = " ".join(points)
            equity_fill = f"0,200 {equity_points} 800,200"

        # Read recent logs
        recent_logs = []
        try:
            log_path = "logs/bot.log"
            if os.path.exists(log_path):
                with open(log_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                    # take the last 50 lines and reverse them so newest is on top
                    recent_logs = [line.strip() for line in lines[-50:]]
                    recent_logs.reverse()
        except Exception:
            pass

        return render(
            "overview",
            title="Overview",
            page="overview",
            stats=stats,
            status=status_detail["status"],
            status_detail=status_detail,
            equity_data=equity_data,
            equity_points=equity_points,
            equity_fill=equity_fill,
            logs=recent_logs,
        )

    @app.route("/positions")
    @login_required
    def positions():
        open_positions = db.get_open_trades()
        return render(
            "positions",
            title="Positions",
            page="positions",
            positions=open_positions,
        )

    @app.route("/graceful-stop", methods=["POST"])
    @login_required
    def graceful_stop():
        # Write a flag file that main.py checks
        try:
            os.makedirs("data", exist_ok=True)
            with open("data/graceful_stop.flag", "w") as f:
                f.write(datetime.now(timezone.utc).isoformat())
            db.set_status("stopping")
        except Exception:
            pass
        return redirect("/positions")

    @app.route("/history")
    @login_required
    def history():
        trades = db.get_recent_trades(limit=200)
        stats = db.get_stats()
        return render(
            "history",
            title="History",
            page="history",
            trades=trades,
            stats=stats,
        )

    # ---- API endpoints (for potential future use) --------------------

    @app.route("/api/stats")
    @login_required
    def api_stats():
        return jsonify(db.get_stats())

    @app.route("/api/equity")
    @login_required
    def api_equity():
        return jsonify(db.get_equity_history())

    # Flask message hack for jinja2 DictLoader
    flask_msgs = []

    @app.before_request
    def _inject_flash():
        nonlocal flask_msgs
        flask_msgs = list(session.pop("_flashes", []) if "_flashes" in session else [])

    return app


# ========================================================================
#  Standalone runner
# ========================================================================

if __name__ == "__main__":
    import yaml
    from dotenv import load_dotenv
    load_dotenv(override=True)

    config = {}
    if os.path.exists("config.yaml"):
        with open("config.yaml") as f:
            config = yaml.safe_load(f)

    app = create_app(config)
    port = config.get("dashboard", {}).get("port", 8050)
    print(f"Dashboard: http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=True)
