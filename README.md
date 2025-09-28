# SUPER-SYSTEM-EYELIDS

## 🧠 CORTEX v3.0 Entry Point System

### Architecture: 7% core + 2% floating cache

Intelligent data routing system with automatic overflow protection and real-time processing.

## 📊 System Components

### Core (7% max):
- `userPreferences/` - User configurations and CORTEX DNA
- `routing-rules/` - Data routing logic and patterns
- `reflex-protocols/` - Automatic reactions and triggers
- `system-config/` - System settings and thresholds

### Floating Cache (2% max):
- `incoming/` - New data entry point
- `processing/` - Data being classified and routed
- `outgoing/` - Ready for distribution to target repos

## 🚀 Features

- **Automatic Overflow Protection** - Prevents system overload
- **Priority Queue** - Critical data processed first
- **Emergency Cleanup** - Automatic cache clearing when > 2%
- **Real-time Monitoring** - Size and performance tracking
- **Async Processing** - Non-blocking operations with asyncio
- **Trigger System** - Automatic reactions to system events

## 📈 Performance Targets

- Processing time: < 10 seconds full cycle
- Cache cleanup: < 100ms
- Uptime target: 99.9%
- Max latency: 5 seconds
- Emergency response: < 1 second

## 🔄 Data Flow

```
1. Input → cache/incoming/ (< 100ms)
2. Processing → cache/processing/ (< 1s)
3. Classification → CORTEX routing (< 2s)
4. Distribution → target repos (< 5s)
5. Cleanup → cache cleared (< 10s)
```

## 🎯 Repository Distribution

```python
DISTRIBUTION = {
    'super-system-eyelids': '7% core + 2% cache',
    'cortex-memory': 'unlimited (all history)',
    'cortex-active': '20% (current projects)',
    'cortex-archive': 'unlimited (compressed old)',
    'project-repos': '100% each'
}
```

## 🔧 Installation

```bash
pip install -r requirements.txt
python eyelids_core.py
```

## 📝 Configuration

Edit `core/system-config/config.json` to adjust:
- Cache limits (default 2%)
- Processing timeouts (default 10s)
- Trigger thresholds (1.5% warning, 2% critical)
- Repository targets

## 📊 Monitoring

Dashboard available at: `http://localhost:8000` (coming soon)

## 🔥 Created by Jean Claude / CORTEX v3.0

*Energy: MAXIMUM! Let's fucking go!*

---

# 💸 Sellable Add-ons (Ready-to-Ship)

The repository now includes ready-to-sell products focused on quick delivery and simple customization.

## 1) Telegram Bot Template (sellable)

- File: `commercial_bot_template.py`
- No external heavy frameworks (std lib only)
- Lead capture to `leads.csv`, subscribers in `subscribers.txt`
- Pricing to offer clients: Basic $299 / Pro $599 / Elite $999

Run:

```bash
TELEGRAM_BOT_TOKEN=123456:ABC python3 commercial_bot_template.py
```

Customize:
- `BOT_NAME`, `COMPANY_NAME`, `TEXTS`, `KEYWORDS`, `FAQ`

## 2) Monitoring as a Service

- File: `monitoring_service.py` (Flask)
- Token auth via header `X-API-Key`
- Stores metrics as JSON Lines in `metrics.db.jsonl`
- Dashboard: `/dashboard`, Health: `/health`
- Pricing: $29 / $59 / $99 per month

Run:

```bash
MONITORING_API_KEY=demo PORT=8088 python3 monitoring_service.py
```

Send metric example:

```bash
curl -X POST 'http://localhost:8088/api/metrics' \
  -H 'Content-Type: application/json' \
  -H 'X-API-Key: demo' \
  -d '{"source":"site","metric":"signup","value":1}'
```

## 3) Landing Page

- File: `landing_page.html`
- Open directly in a browser or host with any static host
- Replace the lead form endpoint with your Formspree/Make/Zapier webhook

## 4) Quick Deploy

- File: `quick_deploy.sh`
- Creates venv, installs Flask, prepares `.env`, runs monitoring and/or bot

```bash
chmod +x quick_deploy.sh
./quick_deploy.sh setup
./quick_deploy.sh monitoring   # start dashboard on http://localhost:8088/dashboard
./quick_deploy.sh bot          # run Telegram bot
./quick_deploy.sh all          # run both
```

## 5) Dependencies

Install dependencies (for monitoring and protocols):

```bash
pip install -r requirements.txt
```

## 6) GitHub Pages (Landing auto-deploy)

Use the provided GitHub Actions workflow to publish `landing_page.html` to GitHub Pages. Enable Pages in repo Settings → Pages → Source: GitHub Actions.