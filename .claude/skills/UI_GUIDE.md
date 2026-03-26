# UI Guide — Quant Trading System

A detailed walkthrough of every page, button, and interaction in the web interface.

---

## Accessing the UI

- **URL:** `http://localhost:8080` (or whatever host your Docker is on)
- **Default credentials:** Username `admin`, Password `admin1234`
- All pages except the login page require authentication

---

## 1. Login Page (`/login`)

A simple centered card with two fields and one button.

| Element | What it does |
|---------|-------------|
| **Username** field | Type your username here |
| **Password** field | Type your password here |
| **Sign In** button | Submits the form. If correct, redirects to Dashboard. If wrong, shows a red error banner. |

After signing in, a session cookie is set in your browser. You stay logged in until you log out or the cookie expires (default: 24 hours).

---

## 2. Common Layout (All Pages Except Login)

Every page shares the same skeleton:

### Top Navigation Bar (fixed at top)

```
[ Quant Trader ]  [ Dashboard ]  [ Strategy Editor ]  [ Backtest ]  [ Settings ]     admin  Logout
```

| Element | What it does |
|---------|-------------|
| **Quant Trader** | Just the app title — not clickable |
| **Dashboard** | Goes to the main dashboard (`/`) |
| **Strategy Editor** | Goes to the code editor (`/editor`) |
| **Backtest** | Goes to the backtest page (`/backtest`) |
| **Settings** | Goes to API key settings (`/settings`) |
| **admin** | Shows your current username |
| **Logout** | Logs you out, returns to login page |

The current page is highlighted with a blue underline.

### Left Sidebar (fixed, 260px wide)

This is the **session manager** — it appears on every page.

```
SESSIONS                    [+]
─────────────────────────────
OVERVIEW
  All Sessions (global view)
─────────────────────────────
ACTIVE SESSIONS
  BTC Momentum Sim    [SIM]
  ● Running · BTCUSDT, ETHUSDT
    [Stop] [Delete]

  AAPL Live           [LIVE]
  ○ Stopped · AAPL, MSFT
    [Start] [Delete]
```

| Element | What it does |
|---------|-------------|
| **[+] button** (green) | Opens the "Create New Session" popup |
| **All Sessions** | Click to switch to global view — Dashboard shows aggregated data across all sessions |
| **Session item** (any row) | Click to **select** that session. The page content (Dashboard, Editor, Backtest) now shows data only for that session. The selected item gets a blue left border. |
| **Status dot** | 🟢 Green = running, ⚫ Gray = stopped, 🔴 Red = error |
| **SIM badge** (yellow) | This is a simulation session (fake money) |
| **LIVE badge** (red) | This is a live trading session (real money!) |
| **Start button** | Starts the session's trading pipeline (data feed → strategy → risk → execution). Only shown when session is stopped. |
| **Stop button** | Stops a running session. Only shown when session is running. |
| **Delete button** | Deletes the session **and all its data** (trades, orders, positions, equity history). Shows a confirmation dialog first. |

The Start/Stop/Delete buttons only appear when you click on a session to select it.

### Create New Session Popup

When you click the **[+]** button, this modal appears:

| Field | What it does |
|-------|-------------|
| **Session Name** | Give your session a human-readable name (e.g. "BTC Momentum Test") |
| **Session Type** dropdown | Choose one of 4 options (see table below) |
| **Symbol Universe** dropdown | Pick a preset group of tickers, or choose "Custom" to type your own |
| **Symbols** text field | The actual comma-separated ticker list. The universe dropdown pre-fills this, but you can edit freely |
| **Starting Budget** | How much fake money to start with (for simulation). Default $10,000 |
| **API Key** field | Only appears for Live session types. Enter your exchange API key |
| **API Secret** field | Only appears for Live session types. Enter your exchange API secret |
| **Cancel** button | Closes the popup without creating anything |
| **Create** button | Creates the session and adds it to the sidebar. The page reloads. |

#### Session Types

| Type | Market | Data Source | Execution | Needs API Keys? |
|------|--------|------------|-----------|----------------|
| **Binance Simulation** | Crypto (BTC, ETH, etc.) | Real Binance WebSocket prices | Fake money, instant fills | No |
| **Alpaca Simulation** | US Stocks (AAPL, MSFT, etc.) | Real yfinance prices (~2s delay) | Fake money, instant fills | No |
| **Binance Live** | Crypto | Real Binance WebSocket prices | Real orders on Binance | Yes |
| **Alpaca Live** | US Stocks | Real yfinance prices | Real orders on Alpaca | Yes |

When you switch between Binance/Alpaca types, the universe dropdown updates to show only relevant presets (crypto presets for Binance, stock presets for Alpaca).

### Toast Notifications

A small popup in the bottom-right corner that appears briefly when you do something:
- **Green** = success (e.g. "Session created", "Session started")
- **Red** = error (e.g. "Failed to start session")

Disappears after 3 seconds.

---

## 3. Dashboard Page (`/`)

The main monitoring page. Shows your portfolio state at a glance.

### Session Banner

If you have a specific session selected in the sidebar, a thin bar at the top shows:
```
Viewing: BTC Momentum Sim
```
If "All Sessions" is selected, this banner is hidden.

### Metric Cards (top row)

Four cards in a row showing key numbers:

| Card | What it shows |
|------|-------------|
| **Total Equity** | Total portfolio value (cash + positions). In dollars. |
| **Daily P&L** | How much you've made or lost today. Green if positive, red if negative. |
| **Open Positions** | How many different symbols you currently hold |
| **Cash** | Available cash not tied up in positions |

### Equity Curve (wide chart)

A **line chart** showing your total equity over time. This is built from periodic snapshots the system takes while a session is running.

- X-axis: time
- Y-axis: portfolio value in dollars
- Blue filled line

### Positions Table

Shows all currently open positions:

| Column | Meaning |
|--------|---------|
| **Symbol** | Which ticker (e.g. BTCUSDT, AAPL) |
| **Qty** | How many units you hold |
| **Entry** | Average price you bought at |
| **Current** | Current market price |
| **P&L** | Unrealized profit/loss. Green = you're up, red = you're down |

### Recent Orders Table

Shows the last 20 orders placed by your strategy:

| Column | Meaning |
|--------|---------|
| **Symbol** | Which ticker |
| **Side** | BUY or SELL |
| **Qty** | Order quantity |
| **Status** | Colored dot + text: 🟢 filled, 🟡 placed, ⚫ pending, 🔴 failed |
| **Time** | When the order was created |

### Kill Switch Button (top-right nav bar)

```
[ Kill Switch: OFF ]     ← green, click to activate
[ Kill Switch: ON  ]     ← red, click to deactivate
```

| State | What it means |
|-------|--------------|
| **OFF** (green) | Trading is active. Strategies can place orders normally. |
| **ON** (red) | Emergency stop! No new orders will be placed. Existing positions are NOT automatically closed — it just prevents new trades. |

Click to toggle. When scoped to a session, it only affects that session. The system also auto-activates the kill switch if drawdown exceeds 5% or daily loss exceeds 3%.

### Auto-Refresh

The dashboard fetches fresh data every **10 seconds** automatically. You'll see a small note at the bottom: "Auto-refreshes every 10 seconds."

---

## 4. Strategy Editor Page (`/editor`)

This is where you write the Python code that decides when to buy and sell.

### Layout

```
┌─────────────────────────────────────────────────────────┐
│ [Validate]  [Deploy]  [Reset to Default]    Ready       │ ← toolbar
├─────────────────────────────────────────────────────────┤
│                                                         │
│              Python code editor                         │ ← CodeMirror
│              (syntax highlighted)                       │
│                                                         │
├─────────────────────────────────────────────────────────┤
│ Validation feedback (hidden until you click Validate)   │ ← feedback panel
├─────────────────────────────────────────────────────────┤
│ ▶ Strategy Reference (click to expand)                  │ ← reference panel
└─────────────────────────────────────────────────────────┘
```

### Toolbar Buttons

| Button | What it does |
|--------|-------------|
| **Validate** | Checks your code for errors WITHOUT deploying. Runs AST (syntax tree) checks: does your class subclass BaseStrategy? Does it implement `on_tick` and `on_bar`? Are your imports allowed? Shows results in the feedback panel below the editor. |
| **Deploy** (green) | Validates AND saves your code. If a session is selected, saves to that session's DB record. If no session selected, saves to the global strategy file. Triggers a hot-reload so the running strategy picks up the new code immediately. |
| **Reset to Default** (yellow) | Replaces the editor content with the built-in momentum strategy example. Does NOT auto-deploy — you still need to click Deploy if you want to use it. |

### Status Badge (right side of toolbar)

| Badge | Meaning |
|-------|---------|
| **Ready** (gray) | Idle, nothing happening |
| **Session strategy loaded** (gray) | Code was loaded from the selected session |
| **Default strategy loaded** (gray) | Code was loaded from the built-in example |
| **Valid** (green) | Last validation passed |
| **Errors found** (red) | Last validation failed |
| **Deployed** (green) | Code was successfully saved and deployed |
| **Deploy failed** (red) | Deploy rejected (usually validation errors) |

### Session Label

When a session is selected in the sidebar, a label appears in the toolbar:
```
Editing for: BTC Momentum Sim
```
This tells you which session's strategy you're editing. Each session has its own saved strategy code.

### Feedback Panel

Appears below the editor after you click Validate or Deploy:
- ✓ Green lines = things that passed
- ✗ Red lines = errors you need to fix
- ⚠ Yellow lines = warnings (non-blocking)

### Strategy Reference Panel

A collapsible section at the very bottom. Click "Strategy Reference" to expand it. Contains:
- The required class interface (`on_tick`, `on_bar` method signatures)
- All fields available on `MarketTick` (symbol, price, volume, timestamp, exchange)
- All fields available on `OHLCVBar` (symbol, open, high, low, close, volume, interval, timestamp)
- How to use `extra_data` (optional custom data pipeline)
- How to return a `TradeSignal` (symbol, signal, strength, strategy_id, metadata)
- List of allowed imports

This is your reference while writing strategies — you don't need to memorize anything.

---

## 5. Backtest Page (`/backtest`)

Test your strategy against historical data without risking money.

### Layout (split view)

```
┌──────────────────────────┬──────────────────┐
│  BACKTEST CONFIGURATION  │  STATUS/RESULTS  │
│  [symbols] [dates]       │                  │
│  [cash] [interval]       │  Performance     │
│  [Run Backtest]          │  Metrics         │
│                          │                  │
│  STRATEGY CODE           │  Equity Curve    │
│  (Python editor)         │  (chart)         │
│                          │                  │
│                          │  Trade Log       │
│                          │  (table)         │
└──────────────────────────┴──────────────────┘
     LEFT PANEL                RIGHT PANEL
```

### Left Panel — Configuration

| Field | What it does |
|-------|-------------|
| **Symbols** | Comma-separated tickers to test on (e.g. `AAPL,MSFT,GOOGL`). Pre-filled from session if one is selected. |
| **Start Date** | Beginning of the test period (default: 2024-01-01) |
| **End Date** | End of the test period (default: 2025-01-01) |
| **Starting Cash** | How much virtual money to start with (default: $10,000) |
| **Bar Interval** dropdown | `Daily (1d)`, `Weekly (1wk)`, or `Monthly (1mo)` — how often strategy receives data points |
| **Run Backtest** button (green) | Downloads historical data from yfinance, replays it through your strategy, and shows results on the right. Shows a spinner while running. |
| **Runtime display** | After completion, shows "Completed in X.Xs" next to the button |

### Left Panel — Strategy Code

A full Python code editor (CodeMirror). Pre-loaded with:
- The selected session's strategy (if a session is selected in sidebar)
- Or the default momentum strategy

You can edit the code here and it will be used for the backtest. Changes here do NOT affect your live/deployed strategy — this is purely for testing.

### Right Panel — Results

Before running a backtest, shows a placeholder: "Configure parameters and click Run Backtest to see results."

After running, shows three sections:

#### Performance Metrics (3×3 grid)

| Metric | What it means |
|--------|-------------|
| **Total Return** | Overall gain/loss as a percentage (e.g. +15.23%) |
| **Annualized** | Total return scaled to a yearly rate |
| **Sharpe Ratio** | Risk-adjusted return. >1 = good, >2 = great, <0 = losing money |
| **Max Drawdown** | Worst peak-to-trough drop (how bad it got at its worst) |
| **Win Rate** | Percentage of trades that were profitable |
| **Profit Factor** | Gross profits ÷ gross losses. >1 = profitable overall |
| **Total Trades** | How many buy+sell trades were executed |
| **Winners** | Number of profitable trades |
| **Losers** | Number of losing trades |

Colors: green = positive/good, red = negative/bad.

#### Equity Curve (chart)

- **Blue line** = total equity over time
- **Gray dashed line** = cash (money not in positions)
- Hover to see exact values at any point

#### Trade Log (table)

Scrollable table of every trade the strategy made:

| Column | Meaning |
|--------|---------|
| **Date** | When the trade happened |
| **Symbol** | Which ticker |
| **Side** | BUY (green) or SELL (red) |
| **Qty** | Number of shares/units |
| **Price** | Execution price |
| **Equity** | Total portfolio value after this trade |

### Status Messages

- **Blue info bar** = "Downloading data and running backtest..." (while running)
- **Red error bar** = Something went wrong (strategy code errors, no data found, etc.)

---

## 6. Settings Page (`/settings`)

Configure global exchange API keys. These are **fallback** keys — used when a session doesn't have its own keys.

### Binance Section

| Element | What it does |
|---------|-------------|
| **Status indicator** | 🟢 "Configured" or ⚫ "Not configured" — shows whether keys are currently set |
| **API Key** field | Your Binance API key |
| **API Secret** field | Your Binance API secret (shown as dots) |
| **Testnet mode** toggle | ON (default) = use Binance testnet (fake money). OFF = real Binance (real money!) |

### Alpaca Section

| Element | What it does |
|---------|-------------|
| **Status indicator** | Same as Binance — green/gray dot |
| **API Key** field | Your Alpaca API key |
| **API Secret** field | Your Alpaca API secret |
| **Paper trading mode** toggle | ON (default) = paper trading (fake money). OFF = real Alpaca (real money!) |

### Save Settings Button

Saves all fields to the server's `.env` file. Shows a green toast "Settings saved" on success.

**Important:** These are global defaults. When you create a Live session using the [+] button in the sidebar, you can provide per-session API keys that override these global ones.

---

## Typical Workflow

Here's how you'd use the system from start to finish:

### 1. Create a simulation session
- Click **[+]** in the sidebar
- Name it something like "BTC Test"
- Select **Binance Simulation**
- Pick **Crypto Top 10** from the universe dropdown (or type your own symbols)
- Set budget to $10,000
- Click **Create**

### 2. Write and test a strategy
- Go to **Backtest** page
- Click on your session in the sidebar
- Edit the strategy code in the editor
- Click **Run Backtest** to see how it performs on historical data
- Tweak the code and re-run until you're happy

### 3. Deploy the strategy
- Go to **Strategy Editor** page
- Make sure your session is selected in the sidebar
- Paste or edit your strategy code
- Click **Validate** to check for errors
- Click **Deploy** to save it to the session

### 4. Start trading
- Click **Start** on your session in the sidebar
- Go to **Dashboard** to watch it trade
- The strategy will now receive live market data and generate buy/sell signals automatically

### 5. Monitor
- Dashboard auto-refreshes every 10 seconds
- Watch the equity curve, positions, and orders
- Use the **Kill Switch** if something goes wrong
