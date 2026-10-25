#!/usr/bin/env bash
# Start the whole Zava Inventory Advisor with one command.
#
#   bash scripts/run_agent.sh          start the agent service (it starts the 3 tool servers) and the web app
#   bash scripts/run_agent.sh stop     stop them
#   bash scripts/run_agent.sh status   show whether they are running
#
# Press Ctrl+C in the terminal that is running it to stop everything.

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOGS="$ROOT/logs"
WORKSHOP="$ROOT/src/python/workshop"
WEB="$ROOT/src/python/web_app"
ACCESS_LIST="${ACCESS_LIST_FILE:-$WORKSHOP/access_list.json}"
AGENT_PORT=8006
WEB_PORT=8005
PIDS="$LOGS/run_agent.pids"

mkdir -p "$LOGS"

port_in_use() { ss -ltn 2>/dev/null | grep -qE "[:.]$1\b"; }

stop_all() {
  if [ -f "$PIDS" ]; then
    while read -r pid; do
      [ -n "$pid" ] && kill -INT "$pid" 2>/dev/null
    done < "$PIDS"
    for _ in $(seq 1 20); do
      port_in_use "$AGENT_PORT" || port_in_use "$WEB_PORT" || break
      sleep 0.5
    done
    rm -f "$PIDS"
  fi
}

case "${1:-start}" in
  stop)
    stop_all
    if port_in_use "$AGENT_PORT" || port_in_use "$WEB_PORT"; then
      echo "Something is still listening on $AGENT_PORT or $WEB_PORT (started some other way). Stop it in its own terminal."
      exit 1
    fi
    echo "Stopped."
    exit 0
    ;;
  status)
    for p in "$AGENT_PORT" "$WEB_PORT"; do
      port_in_use "$p" && echo "port $p: running" || echo "port $p: not running"
    done
    exit 0
    ;;
  start) ;;
  *) echo "Usage: bash scripts/run_agent.sh [start|stop|status]"; exit 2 ;;
esac

# Checks, so a mistake is explained instead of failing silently later.
if port_in_use "$AGENT_PORT" || port_in_use "$WEB_PORT"; then
  echo "Port $AGENT_PORT or $WEB_PORT is already in use. Run: bash scripts/run_agent.sh stop"
  exit 1
fi
if [ ! -f "$ACCESS_LIST" ]; then
  echo "No access list at $ACCESS_LIST."
  echo "Copy src/python/workshop/access_list.example.json to access_list.json and edit the names."
  exit 1
fi
if [ ! -f "$WEB/temp_access_codes.json" ]; then
  echo "No access codes yet. Make them (they print in your terminal; keep them private):"
  echo "  cd src/python/web_app && python temp_access.py generate <name> <name> ..."
  exit 1
fi
if ! timeout 30 az account show >/dev/null 2>&1; then
  echo "Warning: you do not appear to be signed in to Azure. If the agent reports a credential error, run: az login --use-device-code"
fi

cleanup() {
  trap - INT TERM EXIT
  echo; echo "Stopping..."
  stop_all
  echo "Stopped."
}
trap cleanup INT TERM EXIT

: > "$PIDS"

echo "Starting the agent service (and its three tool servers)..."
( cd "$WORKSHOP" && ACCESS_LIST_FILE="$ACCESS_LIST" exec python agent_service.py ) > "$LOGS/agent_service.out" 2>&1 &
AGENT_PID=$!
echo $AGENT_PID >> "$PIDS"

echo "Starting the web app..."
( cd "$WEB" && exec python web_app.py ) > "$LOGS/web_app.out" 2>&1 &
WEB_PID=$!
echo $WEB_PID >> "$PIDS"

# Wait until the agent says it is healthy (up to 90 seconds).
healthy=""
for _ in $(seq 1 45); do
  if curl -fs "http://127.0.0.1:$AGENT_PORT/health" 2>/dev/null | grep -q '"status":"healthy"'; then healthy=1; break; fi
  sleep 2
done
if [ -z "$healthy" ]; then
  echo "The agent did not become healthy. Last lines of its log:"
  tail -n 15 "$LOGS/agent_service.out"
  exit 1
fi
if ! curl -fs -o /dev/null "http://127.0.0.1:$WEB_PORT/health"; then
  echo "The web app did not start. Last lines of its log:"
  tail -n 15 "$LOGS/web_app.out"
  exit 1
fi

echo
echo "Ready."
echo "  Open the chat page:  http://127.0.0.1:$WEB_PORT   (sign in with an access code)"
echo "  Health check:        http://127.0.0.1:$AGENT_PORT/health"
echo "  To share with your team, forward port $WEB_PORT only (never $AGENT_PORT) in the Ports panel."
echo "  Logs: logs/agent_service.out and logs/web_app.out"
echo "Press Ctrl+C to stop everything."

# Stay in the foreground until Ctrl+C, or until one of the two exits on its own.
while kill -0 "$AGENT_PID" 2>/dev/null && kill -0 "$WEB_PID" 2>/dev/null; do
  sleep 2
done
echo "One of the services stopped. Check the logs in logs/."
