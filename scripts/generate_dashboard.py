"""Generate a self-contained static dashboard (dashboard/index.html).

Reads:
  data/directional_arbitrage.json   opportunities detected by run_arbitrage_detection.py
  data/arbitrage_data.json          market metadata (joined for human-readable questions)
  data/trading/*.jsonl + state.json paper-trading journals (full mode only)

Writes:
  dashboard/index.html              fully self-contained page, published to GitHub Pages

Modes:
  default      full dashboard with paper-trading sections
  --lite       analysis-only: no paper-trading sections, no trading journals read
"""
from __future__ import annotations

import argparse
import html
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

HKT = ZoneInfo("Asia/Hong_Kong")

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT_DIR = ROOT / "dashboard"


def load_json(path: Path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def load_jsonl(path: Path):
    rows = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        rows.append(json.loads(line))
                    except Exception:
                        pass
    except FileNotFoundError:
        pass
    return rows


def pct(x):
    try:
        return f"{float(x) * 100:.1f}%"
    except (TypeError, ValueError):
        return "-"


def money(x):
    try:
        return f"${float(x):,.0f}"
    except (TypeError, ValueError):
        return "-"


def build_market_index():
    """Map market id -> human readable question. Only loads needed fields."""
    index = {}
    path = DATA / "arbitrage_data.json"
    if not path.exists():
        return index
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return index
    if isinstance(data, dict):
        data = data.get("data", [])
    for m in data:
        if not isinstance(m, dict):
            continue
        mid = str(m.get("id") or m.get("conditionId") or "")
        q = m.get("question") or m.get("groupItemTitle") or ""
        if mid and q:
            index[mid] = q
    return index


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lite", action="store_true",
                    help="Analysis-only dashboard: hide all paper-trading sections.")
    args = ap.parse_args()
    lite = args.lite

    opportunities = load_json(DATA / "directional_arbitrage.json", [])
    if isinstance(opportunities, dict):
        opportunities = opportunities.get("opportunities", opportunities.get("data", []))
    if not isinstance(opportunities, list):
        opportunities = []

    market_index = build_market_index()

    # Enrich opportunities with readable event names (top 200 by edge only)
    opportunities.sort(key=lambda o: float(o.get("profit_margin") or 0), reverse=True)
    top = opportunities[:200]
    rows = []
    for o in top:
        mo = (o.get("matched_outcomes") or [{}])[0]
        mid = str(o.get("pm_market_id") or "")
        rows.append(
            {
                "event": market_index.get(mid, mid or "unknown market"),
                "outcome": mo.get("pm_outcome", "-"),
                "pm_price": mo.get("pm_price"),
                "sb_prob": mo.get("sb_implied_prob"),
                "edge": o.get("profit_margin"),
                "edge_abs": o.get("profit_margin_absolute"),
                "confidence": o.get("match_confidence"),
                "books": o.get("sportsbook_count"),
                "liquidity": o.get("pm_liquidity") or o.get("liquidity"),
            }
        )

    # Paper trading journals (skipped entirely in lite mode)
    if lite:
        signals, orders, fills, positions, risk_events, state = [], [], [], [], [], {}
        open_list = []
    else:
        trading_dir = DATA / "trading"
        signals = load_jsonl(trading_dir / "signals.jsonl")
        orders = load_jsonl(trading_dir / "orders.jsonl")
        fills = load_jsonl(trading_dir / "fills.jsonl")
        positions = load_jsonl(trading_dir / "positions.jsonl")
        risk_events = load_jsonl(trading_dir / "risk_events.jsonl")
        state = load_json(trading_dir / "state.json", {})

        # Open positions: last snapshot per market from positions journal
        open_pos = {}
        for p in positions:
            key = str(p.get("market_id") or p.get("condition_id") or p.get("id") or "")
            if key:
                open_pos[key] = p
        open_list = [p for p in open_pos.values() if float(p.get("shares") or p.get("size") or 0) != 0]

    def slim(entries, fields, limit=80):
        out = []
        for e in entries[-limit:]:
            out.append({k: e.get(k) for k in fields})
        return out

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "opportunities": rows,
        "stats": {
            "n_opportunities": len(opportunities),
            "max_edge": max((float(o.get("profit_margin") or 0) for o in opportunities), default=0),
            "n_signals": len(signals),
            "n_orders": len(orders),
            "n_fills": len(fills),
            "n_open_positions": len(open_list),
            "n_risk_denied": sum(1 for r in risk_events if str(r.get("decision", "")).lower() in ("denied", "deny", "rejected")),
        },
        "fills": slim(fills, ["timestamp", "time", "market_id", "side", "outcome", "price", "shares", "size", "notional"], 80),
        "signals": slim(signals, ["timestamp", "time", "market_id", "direction", "outcome", "edge", "profit_margin", "confidence"], 80),
        "positions": slim(open_list, ["market_id", "outcome", "side", "shares", "size", "avg_price", "entry_price", "unrealized_pnl", "status"], 100),
        "state": state if isinstance(state, dict) else {},
    }

    data_json = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    now_hkt = datetime.now(HKT).strftime("%Y-%m-%d %H:%M")

    if lite:
        badge = "機會掃描"
        update_note = "（手動觸發更新）"
        disclaimer = "⚠️ 純數據分析，只供研究參考，唔構成任何投資建議。本版本不設任何交易功能（連紙交易都冇）。"
        paper_sections = ""
        paper_js = ""
        cards_js = (
            '  [D.stats.n_opportunities, "方向性機會"],\n'
            '  [pct(D.stats.max_edge), "最高邊際"],\n'
            '  [D.stats.n_signals, "訊號總數"],'
        )
    else:
        badge = "PAPER 紙交易"
        update_note = "（手動觸發更新）"
        disclaimer = "⚠️ 紙上模擬交易，只供研究參考，唔構成任何投資建議。真實交易功能已被鎖定（paper mode）。"
        paper_sections = """
<h2>📒 紙交易 — 持倉</h2>
<div class="wrap"><table><thead><tr><th>市場</th><th>方向</th><th class="num">數量</th><th class="num">均價</th><th>狀態</th></tr></thead>
<tbody id="pos"></tbody></table></div>

<h2>🧾 紙交易 — 最近成交</h2>
<div class="wrap"><table><thead><tr><th>時間</th><th>市場</th><th>方向</th><th class="num">價</th><th class="num">數量</th></tr></thead>
<tbody id="fills"></tbody></table></div>
"""
        paper_js = """document.getElementById("pos").innerHTML = D.positions.map(p => `
<tr><td>${esc(p.market_id)}</td><td>${esc(p.outcome || p.side)}</td>
<td class="num">${p.shares ?? p.size ?? "-"}</td><td class="num">${p.avg_price ?? p.entry_price ?? "-"}</td>
<td>${esc(p.status || "open")}</td></tr>`).join("")
|| `<tr><td colspan="5" style="color:var(--dim)">暫無持倉</td></tr>`;

document.getElementById("fills").innerHTML = D.fills.slice().reverse().map(f => `
<tr><td>${esc(f.timestamp || f.time || "")}</td><td>${esc(f.market_id)}</td>
<td>${esc(f.side || f.outcome)}</td><td class="num">${f.price ?? "-"}</td>
<td class="num">${f.shares ?? f.size ?? "-"}</td></tr>`).join("")
|| `<tr><td colspan="5" style="color:var(--dim)">暫無成交記錄</td></tr>`;"""
        cards_js = (
            '  [D.stats.n_opportunities, "方向性機會"],\n'
            '  [pct(D.stats.max_edge), "最高邊際"],\n'
            '  [D.stats.n_signals, "訊號總數"],\n'
            '  [D.stats.n_fills, "紙成交"],\n'
            '  [D.stats.n_open_positions, "未平倉"],\n'
            '  [D.stats.n_risk_denied, "風控否決"],'
        )

    page = """<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Polymarket Sports Arbitrage Bot</title>
<style>
:root {{--bg:#0d1117;--card:#161b22;--line:#30363d;--txt:#e6edf3;--dim:#8b949e;--acc:#58a6ff;--grn:#3fb950;--red:#f85149;--amb:#d29922;}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--txt);font-family:-apple-system,'Segoe UI',Roboto,'Noto Sans TC',sans-serif;padding:16px;max-width:1200px;margin:auto}}
h1{{font-size:22px;margin:8px 0}} h2{{font-size:17px;margin:26px 0 10px;color:var(--acc)}}
.meta{{color:var(--dim);font-size:13px;margin-bottom:4px}}
.badge{{display:inline-block;padding:3px 10px;border-radius:20px;font-size:12px;font-weight:700;background:#1f3a1f;color:var(--grn);border:1px solid var(--grn);margin-left:8px;vertical-align:middle}}
.warn{{background:#2a2305;border:1px solid var(--amb);color:#e8c468;border-radius:8px;padding:10px 14px;font-size:13px;margin:14px 0}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:14px 0}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px}}
.card .v{{font-size:22px;font-weight:700}} .card .l{{font-size:12px;color:var(--dim);margin-top:4px}}
table{{width:100%;border-collapse:collapse;font-size:13px;background:var(--card);border:1px solid var(--line);border-radius:10px;overflow:hidden}}
th,td{{padding:9px 10px;text-align:left;border-bottom:1px solid var(--line)}}
th{{color:var(--dim);font-weight:600;background:#1c2128;position:sticky;top:0}}
tr:hover td{{background:#1c2128}} .pos{{color:var(--grn);font-weight:700}} .num{{text-align:right;font-variant-numeric:tabular-nums}}
.wrap{{overflow-x:auto;border-radius:10px}} .foot{{color:var(--dim);font-size:12px;margin:26px 0 10px;line-height:1.7}}
a{{color:var(--acc)}}
</style>
</head>
<body>
<h1>Polymarket Sports 套利機械人 <span class="badge">__BADGE__</span></h1>
<div class="meta">數據更新：__NOW_HKT____UPDATE_NOTE__｜ Polymarket 價格 vs 莊家賠率方向性機會</div>
<div class="warn">__DISCLAIMER__</div>

<h2>📊 概覽</h2>
<div class="cards" id="cards"></div>

<h2>🎯 方向性機會（按預期邊際排序，頭 30）</h2>
<div class="wrap"><table><thead><tr>
<th>賽事</th><th>方向</th><th class="num">PM 價</th><th class="num">莊家隱含</th>
<th class="num">邊際</th><th class="num">信心</th><th class="num">莊家數</th><th class="num">流動性</th>
</tr></thead><tbody id="opps"></tbody></table></div>
__PAPER_SECTIONS__

<div class="foot">
數據來源：Polymarket 官方 Gamma API（市場數據）＋ The Odds API（第三方莊家賠率）。<br>
機會定義：當 Polymarket 價格低於莊家隱含概率達閾值（預設 2%），列為方向性機會；傳統無風險套利唔適用（Polymarket 價格恆等於 1）。<br>
原始碼：<a href="https://github.com/Danielsoldev/Polymaket-Sports-Trading-Bot">Danielsoldev/Polymaket-Sports-Trading-Bot</a>（已修復 Gamma API 分頁）。
</div>

<script>
const D = __DATA_JSON__;
const esc = s => String(s ?? "-").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const pct = x => (x === null || x === undefined || x === "" || isNaN(+x)) ? "-" : (+x * 100).toFixed(1) + "%";
const money = x => (x === null || x === undefined || x === "" || isNaN(+x)) ? "-" : "$" + (+x).toLocaleString("en-US", {maximumFractionDigits: 0});

document.getElementById("cards").innerHTML = [
__CARDS_JS__
].map(([v, l]) => `<div class="card"><div class="v">${v}</div><div class="l">${l}</div></div>`).join("");

document.getElementById("opps").innerHTML = D.opportunities.slice(0, 30).map(o => `
<tr><td>${esc(o.event)}</td><td>${esc(o.outcome)}</td>
<td class="num">${(+o.pm_price || 0).toFixed(3)}</td><td class="num">${pct(o.sb_prob)}</td>
<td class="num pos">${pct(o.edge)}</td><td class="num">${pct(o.confidence)}</td>
<td class="num">${o.books ?? "-"}</td><td class="num">${money(o.liquidity)}</td></tr>`).join("")
|| `<tr><td colspan="8" style="color:var(--dim)">今次運行未搵到符合閾值嘅機會</td></tr>`;

__PAPER_JS__
</script>
</body>
</html>
"""
    page = (page.replace("__NOW_HKT__", html.escape(now_hkt))
                .replace("__UPDATE_NOTE__", update_note)
                .replace("__BADGE__", badge)
                .replace("__DISCLAIMER__", disclaimer)
                .replace("__PAPER_SECTIONS__", paper_sections)
                .replace("__CARDS_JS__", cards_js)
                .replace("__PAPER_JS__", paper_js)
                .replace("__DATA_JSON__", data_json))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "index.html").write_text(page, encoding="utf-8")
    extra = "" if lite else f", {len(fills)} fills"
    print(f"Dashboard written: {OUT_DIR / 'index.html'} "
          f"({len(opportunities)} opportunities{extra}, lite={lite})")


if __name__ == "__main__":
    main()
