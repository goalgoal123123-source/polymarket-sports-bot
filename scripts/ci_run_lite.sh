#!/usr/bin/env bash
# CI pipeline (LITE): fetch -> compare -> detect -> dashboard
# Analysis only. No paper trading, no journals, no risk engine.
# Runs on GitHub Actions (free tier), manual trigger only.
set -euo pipefail

cd "$(dirname "$0")/.."
export NO_PROXY="localhost,127.0.0.1"
unset no_proxy || true

echo "=== [1/5] Fetch Polymarket sports markets ==="
python -m poly_sports.data_fetching.fetch_sports_markets

echo "=== [2/5] Filter arbitrage universe ==="
python -m poly_sports.data_fetching.fetch_sports_markets filter data/arbitrage_data.json data || true

echo "=== [3/5] Fetch sportsbook odds (quota-guarded) ==="
SKIP_ODDS=0
if [ -z "${ODDS_API_KEY:-}" ]; then
  echo "No ODDS_API_KEY set - skipping sportsbook odds (comparison will reuse previous file if present)."
  SKIP_ODDS=1
else
  # /v4/sports does NOT consume quota; check remaining credits first.
  REMAINING=$(curl -s -D - -o /dev/null \
    "https://api.the-odds-api.com/v4/sports?apiKey=${ODDS_API_KEY}" \
    | grep -i "^x-requests-remaining:" | tr -d '\r' | awk '{print $2}')
  echo "The Odds API requests remaining: ${REMAINING:-unknown}"
  # One odds request per sport; keep a safety buffer of 40.
  if [ -n "${REMAINING:-}" ] && [ "$REMAINING" -lt 40 ] 2>/dev/null; then
    echo "Quota too low (<40) - skipping odds refresh to preserve credits."
    SKIP_ODDS=1
  fi
fi

if [ "$SKIP_ODDS" = "0" ]; then
  python -m poly_sports.data_fetching.fetch_odds_comparison || \
    echo "WARN: odds comparison failed, continuing with previous data if any."
else
  echo "Skipped."
fi

echo "=== [4/5] Detect directional opportunities ==="
if [ -f data/arbitrage_comparison.json ]; then
  python scripts/run_arbitrage_detection.py --sort-by profit_margin || \
    echo "WARN: detection failed."
else
  echo "No comparison data available - writing empty opportunities file."
  echo "[]" > data/directional_arbitrage.json
fi

echo "=== [5/5] Generate dashboard (lite, analysis-only) ==="
python scripts/generate_dashboard.py --lite

echo "=== Lite pipeline done ==="
ls -la data/directional_arbitrage.json dashboard/index.html 2>/dev/null || true
