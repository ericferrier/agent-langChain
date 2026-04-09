#!/usr/bin/env bash
set -u

OLLAMA_URL="${OLLAMA_URL:-http://localhost:11434}"
APP_URL="${APP_URL:-http://localhost:8000}"
NODE_URL="${NODE_URL:-http://localhost:3000}"
OLLAMA_MODEL="${OLLAMA_MODEL:-mistral:7b}"
BATCH_ID="${BATCH_ID:-}"
CONNECT_TIMEOUT="${CONNECT_TIMEOUT:-3}"
QUICK_MODE="${QUICK_MODE:-0}"

# Per-step max times in seconds
MAX_OLLAMA_TAGS="${MAX_OLLAMA_TAGS:-10}"
MAX_OLLAMA_GEN="${MAX_OLLAMA_GEN:-90}"
MAX_APP_HEALTH="${MAX_APP_HEALTH:-10}"
MAX_APP_RAG="${MAX_APP_RAG:-240}"
MAX_NODE_HEALTH="${MAX_NODE_HEALTH:-10}"
MAX_NODE_VERIFY="${MAX_NODE_VERIFY:-240}"

if [[ "$QUICK_MODE" == "1" ]]; then
  MAX_OLLAMA_GEN="30"
  MAX_APP_RAG="45"
  MAX_NODE_VERIFY="45"
fi

PASS=0
FAIL=0
WARN=0

line() {
  printf '%s\n' "------------------------------------------------------------"
}

note() {
  printf '%s\n' "$1"
}

run_probe() {
  local name="$1"
  local method="$2"
  local url="$3"
  local max_time="$4"
  local data="${5:-}"

  local body_file err_file curl_out http_code total_time
  body_file="$(mktemp)"
  err_file="$(mktemp)"

  printf 'RUN   %-24s max=%ss\n' "$name" "$max_time"

  if [[ "$method" == "GET" ]]; then
    curl_out="$(curl -sS --connect-timeout "$CONNECT_TIMEOUT" --max-time "$max_time" \
      -o "$body_file" -w '%{http_code} %{time_total}' "$url" 2>"$err_file")"
  else
    curl_out="$(curl -sS --connect-timeout "$CONNECT_TIMEOUT" --max-time "$max_time" \
      -X "$method" -H 'Content-Type: application/json' \
      -d "$data" -o "$body_file" -w '%{http_code} %{time_total}' "$url" 2>"$err_file")"
  fi
  local curl_code=$?

  if [[ $curl_code -ne 0 ]]; then
    FAIL=$((FAIL + 1))
    printf 'FAIL  %-24s curl_exit=%s error=%s\n' "$name" "$curl_code" "$(tr '\n' ' ' < "$err_file")"
    rm -f "$body_file" "$err_file"
    return 1
  fi

  http_code="${curl_out%% *}"
  total_time="${curl_out##* }"
  local preview
  preview="$(head -c 180 "$body_file" | tr '\n' ' ')"

  if [[ "$http_code" =~ ^2[0-9][0-9]$ ]]; then
    PASS=$((PASS + 1))
    printf 'PASS  %-24s status=%s time=%ss\n' "$name" "$http_code" "$total_time"
  elif [[ "$http_code" =~ ^4[0-9][0-9]$ ]]; then
    WARN=$((WARN + 1))
    printf 'WARN  %-24s status=%s time=%ss body=%s\n' "$name" "$http_code" "$total_time" "$preview"
  else
    FAIL=$((FAIL + 1))
    printf 'FAIL  %-24s status=%s time=%ss body=%s\n' "$name" "$http_code" "$total_time" "$preview"
  fi

  rm -f "$body_file" "$err_file"
}

line
note "Smoke Timeout Probe"
note "OLLAMA_URL=$OLLAMA_URL"
note "APP_URL=$APP_URL"
note "NODE_URL=$NODE_URL"
line

run_probe "ollama tags" "GET" "$OLLAMA_URL/api/tags" "$MAX_OLLAMA_TAGS"
run_probe "ollama generate tiny" "POST" "$OLLAMA_URL/api/generate" "$MAX_OLLAMA_GEN" \
  "{\"model\":\"$OLLAMA_MODEL\",\"prompt\":\"Reply with OK only.\",\"stream\":false,\"options\":{\"num_predict\":16,\"temperature\":0}}"

run_probe "app health" "GET" "$APP_URL/health" "$MAX_APP_HEALTH"
run_probe "app rag query" "POST" "$APP_URL/rag/query" "$MAX_APP_RAG" \
  '{"query":"Return one short sentence confirming service health.","tier":"broad"}'

run_probe "node health" "GET" "$NODE_URL/" "$MAX_NODE_HEALTH"
if [[ -n "$BATCH_ID" ]]; then
  run_probe "node verify" "GET" "$NODE_URL/verify/$BATCH_ID" "$MAX_NODE_VERIFY"
else
  note "INFO  node verify skipped (set BATCH_ID=<existing id> to test end-to-end verify path)"
fi

line
note "Summary: pass=$PASS warn=$WARN fail=$FAIL"
if [[ $FAIL -gt 0 ]]; then
  note "Result: FAIL (one or more probes failed)"
  exit 1
fi

if [[ $WARN -gt 0 ]]; then
  note "Result: WARN (no transport failures, but non-2xx responses exist)"
  exit 0
fi

note "Result: PASS"
exit 0
