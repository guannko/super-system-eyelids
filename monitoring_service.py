#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Monitoring Service (Sellable, Simple)

Features:
- Token auth via MONITORING_API_KEY (default: demo)
- POST /api/metrics to submit metrics (JSON)
- GET  /api/stats   to retrieve aggregated stats
- GET  /dashboard   simple HTML dashboard
- GET  /health      health check
- Data stored as JSON Lines (metrics.db.jsonl) for simplicity
- Rotating logs (monitoring_service.log)

Pricing (to present to clients):
- Starter $29/month (up to 3 sources)
- Growth  $59/month (up to 10 sources)
- Scale   $99/month (up to 30 sources)

Run:
  MONITORING_API_KEY=demo PORT=8088 python3 monitoring_service.py

Customize:
- Change BRAND, PRICING_TEXT, and DASHBOARD_FIELDS
- Add simple auth rule in `verify_token`
"""

import os
import json
import time
import threading
from datetime import datetime
from typing import Dict, Any, List

from flask import Flask, request, jsonify, Response
import logging
from logging.handlers import RotatingFileHandler

# ===================== CONFIG =====================
BRAND = "Acme Monitoring"
PRICING_TEXT = (
    "Starter $29/mo • Growth $59/mo • Scale $99/mo — отмена в любой момент"
)
DB_FILE = "metrics.db.jsonl"
LOG_FILE = "monitoring_service.log"
DASHBOARD_FIELDS = ["source", "metric", "value", "ts"]

API_KEY = os.getenv("MONITORING_API_KEY", "demo")
PORT = int(os.getenv("PORT", "8088"))

# ===================== APP & LOGGING =====================
app = Flask(__name__)

logger = logging.getLogger("MonitoringService")
logger.setLevel(logging.INFO)
if not logger.handlers:
    fh = RotatingFileHandler(LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3)
    fh.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    logger.addHandler(fh)
    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    logger.addHandler(ch)

_db_lock = threading.Lock()

# ===================== HELPERS =====================

def verify_token(req: request) -> bool:
    token = req.headers.get("X-API-Key") or req.args.get("token")
    return token == API_KEY


def append_metric(record: Dict[str, Any]) -> None:
    with _db_lock:
        with open(DB_FILE, "a") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def load_recent(limit: int = 500) -> List[Dict[str, Any]]:
    if not os.path.exists(DB_FILE):
        return []
    results: List[Dict[str, Any]] = []
    with _db_lock:
        try:
            with open(DB_FILE, "r") as f:
                for line in f.readlines()[-limit:]:
                    try:
                        results.append(json.loads(line))
                    except Exception:
                        continue
        except Exception:
            return []
    return results


def aggregate_stats(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    total = len(records)
    per_source: Dict[str, int] = {}
    per_metric: Dict[str, int] = {}
    for r in records:
        s = str(r.get("source", "unknown"))
        m = str(r.get("metric", "unknown"))
        per_source[s] = per_source.get(s, 0) + 1
        per_metric[m] = per_metric.get(m, 0) + 1
    return {
        "total": total,
        "sources": per_source,
        "metrics": per_metric,
        "pricing": PRICING_TEXT,
        "brand": BRAND,
        "ts": int(time.time()),
    }


# ===================== ROUTES =====================

@app.route("/health", methods=["GET"])
def health() -> Response:
    return jsonify({"status": "ok", "brand": BRAND})


@app.route("/api/metrics", methods=["POST"])
def api_metrics() -> Response:
    if not verify_token(request):
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    try:
        payload = request.get_json(force=True, silent=False)
        if not isinstance(payload, dict):
            raise ValueError("JSON body must be an object")
        record = {
            "source": payload.get("source", "unknown"),
            "metric": payload.get("metric", "event"),
            "value": payload.get("value", 1),
            "details": payload.get("details", {}),
            "ts": payload.get("ts") or int(time.time()),
            "received_at": datetime.utcnow().isoformat() + "Z",
        }
        append_metric(record)
        logger.info(f"metric: {record['source']} {record['metric']}={record['value']}")
        return jsonify({"ok": True})
    except Exception as e:
        logger.error(f"/api/metrics failed: {e}")
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/stats", methods=["GET"])
def api_stats() -> Response:
    if not verify_token(request):
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    recs = load_recent(2000)
    return jsonify({"ok": True, "stats": aggregate_stats(recs)})


@app.route("/dashboard", methods=["GET"])
def dashboard() -> Response:
    recs = load_recent(200)
    head = "".join(f"<th>{f}</th>" for f in DASHBOARD_FIELDS)
    rows = []
    for r in recs:
        row = "".join(f"<td>{r.get(f, '')}</td>" for f in DASHBOARD_FIELDS)
        rows.append(f"<tr>{row}</tr>")
    html = f"""
    <!doctype html>
    <html lang=\"ru\">
    <head>
      <meta charset=\"utf-8\" />
      <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
      <title>{BRAND} — Dashboard</title>
      <style>
        body {{ font-family: Inter, system-ui, Arial; margin: 0; background: #0b1220; color: #eaf0ff; }}
        header {{ padding: 20px; background: #0f172a; box-shadow: inset 0 -1px 0 #1e293b; }}
        h1 {{ margin: 0; font-size: 20px; }}
        .wrap {{ padding: 20px; }}
        .pricing {{ opacity: .9; margin-top: 6px; font-size: 13px; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 16px; }}
        th, td {{ border-bottom: 1px solid #1e293b; padding: 8px 10px; font-size: 13px; }}
        th {{ text-align: left; color: #94a3b8; }}
      </style>
    </head>
    <body>
      <header>
        <h1>{BRAND} — Live Dashboard</h1>
        <div class=\"pricing\">{PRICING_TEXT}</div>
      </header>
      <div class=\"wrap\">
        <table>
          <thead><tr>{head}</tr></thead>
          <tbody>{''.join(rows) if rows else '<tr><td colspan=4>No data</td></tr>'}</tbody>
        </table>
      </div>
    </body>
    </html>
    """
    return Response(html, mimetype="text/html")


# ===================== MAIN =====================
if __name__ == "__main__":
    logger.info(f"Starting {BRAND} on port {PORT}")
    app.run(host="0.0.0.0", port=PORT)
