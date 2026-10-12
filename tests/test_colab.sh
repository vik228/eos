#!/usr/bin/env bash
# Colab scripts: setup, connect reuse/create, stop, status. All remote calls
# go through stub colab/ssh binaries; no spend, no network.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp="$(mktemp -d)"
tmp="$(cd "$tmp" && pwd -P)"
trap 'rm -rf "$tmp"; pkill -f "FAKE-COLAB-FWD" 2>/dev/null || true; pkill -f "stub-server.py" 2>/dev/null || true' EXIT

fail() { echo "FAIL: $*" >&2; exit 1; }

PORT="$(python3 -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])')"
export EOS_COLAB_LOCAL_PORT="$PORT"
export HOME="$tmp/home"
mkdir -p "$HOME"

stubbin="$tmp/stubbin"
mkdir -p "$stubbin"

# Stub colab CLI: sessions/new/stop/version/usage driven by files.
cat >"$stubbin/colab" <<'STUB'
#!/usr/bin/env bash
state_dir="${STUB_STATE:?}"
case "${1:-}" in
  --help) echo "Usage: colab"; exit 0 ;;
  version) echo "0.7.4"; exit 0 ;;
  sessions)
    if [[ -f "$state_dir/session-active" ]]; then
      cat "$state_dir/session-active"
      exit 0
    fi
    echo "stub colab: not authenticated" >&2
    exit 1
    ;;
  new) printf 'created %s\n' "$*" >>"$state_dir/calls"; touch "$state_dir/session-active"; exit 0 ;;
  stop) printf 'stopped %s\n' "$*" >>"$state_dir/calls"; rm -f "$state_dir/session-active"; exit 0 ;;
  usage) printf 'Current balance: 10 compute units\n'; exit 0 ;;
  ssh) echo "stub colab must not run ssh bridge" >&2; exit 1 ;;
  *) echo "stub colab: unknown $*" >&2; exit 2 ;;
esac
STUB
chmod +x "$stubbin/colab"

# Stub ssh: remote curl checks succeed, -N -f forward is a no-op success.
cat >"$stubbin/ssh" <<'STUB'
#!/usr/bin/env bash
for arg in "$@"; do
  [[ "$arg" == *"curl"* ]] && exit 0
done
exit 0
STUB
chmod +x "$stubbin/ssh"

export STUB_STATE="$tmp/stubstate"
mkdir -p "$STUB_STATE"
export EOS_ROOT="$ROOT" EOS_COLAB_BIN="$stubbin/colab" EOS_SSH_BIN="$stubbin/ssh"
export EOS_STATE_DIR="$tmp/state" EOS_COLAB_SESSION=eos EOS_COLAB_GPU=T4
export EOS_COLAB_REMOTE_PORT=18888

# 1. setup-colab with no auth: ssh config written, backup taken, instruction shown.
export EOS_COLAB_BIN="$stubbin/colab"
mkdir -p "$HOME/.ssh"
printf '# existing user config\n' >"$HOME/.ssh/config"
out="$(EOS_ROOT="$ROOT" "$ROOT/scripts/setup-colab" 2>&1)"
[[ "$out" == *"ssh config updated"* || "$out" == *"ssh config created"* ]] || fail "setup did not write ssh config: $out"
[[ "$out" == *"not authenticated yet"* ]] || fail "setup did not report missing auth: $out"
grep -q "Include ~/.ssh/eos-colab.conf" "$HOME/.ssh/config" || fail "Include missing"
grep -q "ProxyCommand $ROOT/scripts/colab ssh --proxy-mode" "$HOME/.ssh/eos-colab.conf" || fail "ProxyCommand wrong"
[[ -n "$(ls "$HOME/.ssh"/config.eos-backup-* 2>/dev/null)" ]] || fail "no ssh config backup"
[[ -f "$HOME/.ssh/eos_colab_ed25519" ]] || fail "no dedicated key generated"
[[ ! -e "$HOME/.ssh/id_ed25519" ]] || fail "default identity touched"
grep -q "IdentityFile $HOME/.ssh/eos_colab_ed25519" "$HOME/.ssh/eos-colab.conf" || fail "IdentityFile not pinned"
grep -q "IdentitiesOnly yes" "$HOME/.ssh/eos-colab.conf" || fail "IdentitiesOnly missing"

# 2. setup-colab is idempotent and reports auth when present.
echo "[?] eos | Hardware: CPU" >"$STUB_STATE/session-active"
out="$(EOS_ROOT="$ROOT" "$ROOT/scripts/setup-colab" 2>&1)"
[[ "$out" == *"ssh config ok"* ]] || fail "rerun not idempotent: $out"
[[ "$out" == *"auth ok"* ]] || fail "auth not detected: $out"

# 3. connect without --create and no session exits 3.
rm -f "$STUB_STATE/session-active"
rc=0
EOS_ROOT="$ROOT" "$ROOT/scripts/colab-connect" >/dev/null 2>&1 || rc=$?
[[ "$rc" == 3 ]] || fail "missing session should exit 3, got $rc"

# Token-aware stub server: /api/kernels needs the token from $STUB_TOKEN_FILE
# (exact match); a missing file bootstraps by accepting any non-empty token.
# Anything else answers 404, so curl -f checks are meaningful.
cat >"$tmp/stub-server.py" <<'PY'
import http.server
import os
import urllib.parse


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        token = query.get("token", [""])[0]
        try:
            with open(os.environ["STUB_TOKEN_FILE"]) as handle:
                expected = handle.read().strip()
            strict = True
        except OSError:
            expected = None
            strict = False
        if parsed.path.startswith("/api/kernels"):
            if strict:
                ok = bool(expected) and token == expected
            else:
                ok = bool(token)
            code = 200 if ok else 403
            body = b"[]" if ok else b"{}"
        else:
            code, body = 404, b"{}"
        self.send_response(code)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


exported = os.environ.get("STUB_TOKEN_FILE", "")
http.server.HTTPServer(("127.0.0.1", int(os.environ.get("STUB_PORT", "18989"))), Handler).serve_forever()
PY

start_stub_server() {
  STUB_TOKEN_FILE="$tmp/stub-token" STUB_PORT="$PORT" python3 "$tmp/stub-server.py" >/dev/null 2>&1 &
  http_pid=$!
  sleep 1
}
rm -f "$tmp/stub-token"

# 4. connect --create makes a session, starts server, forwards, verifies.
rm -f "$STUB_STATE/session-active" "$STUB_STATE/calls"
start_stub_server
bash -c 'exec -a "FAKE-COLAB-FWD ssh -L '"$PORT"':127.0.0.1:18888" sleep 60' &
sleep_pid=$!
out="$(EOS_ROOT="$ROOT" "$ROOT/scripts/colab-connect" --create 2>&1)"
grep -q "created.*-s eos" "$STUB_STATE/calls" || fail "session not created: $(cat "$STUB_STATE/calls" 2>/dev/null)"
grep -q "\-\-gpu T4" "$STUB_STATE/calls" || fail "gpu flag not passed: $(cat "$STUB_STATE/calls" 2>/dev/null)"
[[ "$out" == *"SESSION=eos"* ]] || fail "no SESSION line: $out"
[[ "$out" == *"CREATED=1"* ]] || fail "create should report CREATED=1: $out"
[[ "$out" == *"LOCAL_PORT=$PORT"* ]] || fail "no port line: $out"
[[ "$out" == *"CREATED="* ]] || fail "no CREATED line: $out"
token="$(printf '%s\n' "$out" | sed -n 's/^TOKEN=//p')"
[[ -n "$token" ]] || fail "no TOKEN line"
[[ -f "$EOS_STATE_DIR/colab/forward.env" ]] || fail "no state file"
# shellcheck source=/dev/null
source "$EOS_STATE_DIR/colab/forward.env"
[[ "$STATE_SESSION" == "eos" && "$STATE_LOCAL_PORT" == "$PORT" && -n "$STATE_TOKEN" && -n "$STATE_PID" ]] \
  || fail "state file wrong: $(cat "$EOS_STATE_DIR/colab/forward.env")"
kill "$http_pid" "$sleep_pid" 2>/dev/null || true

# 5. second connect reuses the live forward (same token, CREATED preserved).
printf '%s' "$token" >"$tmp/stub-token"
start_stub_server
bash -c 'exec -a "FAKE-COLAB-FWD ssh -L '"$PORT"':127.0.0.1:18888" sleep 60' &
sleep_pid=$!
# point the recorded pid at the live fake forward
sed -i.bak "s/^STATE_PID=.*/STATE_PID=$sleep_pid/" "$EOS_STATE_DIR/colab/forward.env"
out2="$(EOS_ROOT="$ROOT" "$ROOT/scripts/colab-connect" 2>&1)"
token2="$(printf '%s\n' "$out2" | sed -n 's/^TOKEN=//p')"
[[ "$token2" == "$token" ]] || fail "reuse changed token: $token2 vs $token"
[[ "$out2" == *"CREATED=1"* ]] || fail "reuse must preserve CREATED=1: $out2"
kill "$http_pid" "$sleep_pid" 2>/dev/null || true

# 6. token verification: a tampered token fails the checks.
start_stub_server
bash -c 'exec -a "FAKE-COLAB-FWD ssh -L '"$PORT"':127.0.0.1:18888" sleep 60' &
sleep_pid=$!
sed -i.bak "s/^STATE_PID=.*/STATE_PID=$sleep_pid/" "$EOS_STATE_DIR/colab/forward.env"
sed -i.bak "s/^STATE_TOKEN=.*/STATE_TOKEN=tampered/" "$EOS_STATE_DIR/colab/forward.env"
status_out="$(EOS_ROOT="$ROOT" "$ROOT/scripts/colab-status" 2>&1 || true)"
[[ "$status_out" == *"server=unreachable"* ]] || fail "tampered token not detected: $status_out"
sed -i.bak "s/^STATE_TOKEN=.*/STATE_TOKEN=$token/" "$EOS_STATE_DIR/colab/forward.env"
status_out="$(EOS_ROOT="$ROOT" "$ROOT/scripts/colab-status" 2>&1 || true)"
[[ "$status_out" == *"server=ready"* ]] || fail "valid token not accepted: $status_out"
kill "$http_pid" "$sleep_pid" 2>/dev/null || true

# 7. exact session match: "eos2" must not satisfy session "eos".
printf '[?] eos2 | Hardware: T4\n' >"$STUB_STATE/session-active"
status_out="$(EOS_COLAB_SESSION=eos EOS_ROOT="$ROOT" "$ROOT/scripts/colab-status" 2>&1 || true)"
[[ "$status_out" == *"session=none"* ]] || fail "substring session matched: $status_out"
printf '[?] eos | Hardware: T4\n' >"$STUB_STATE/session-active"

# 8. status reports and stop cleans up.
EOS_ROOT="$ROOT" "$ROOT/scripts/colab-status" >/dev/null 2>&1 || true
bash -c 'exec -a "FAKE-COLAB-FWD ssh -L '"$PORT"':127.0.0.1:18888" sleep 60' &
sleep_pid=$!
sed -i.bak "s/^STATE_PID=.*/STATE_PID=$sleep_pid/" "$EOS_STATE_DIR/colab/forward.env"
EOS_ROOT="$ROOT" "$ROOT/scripts/colab-stop" >/dev/null
[[ ! -f "$EOS_STATE_DIR/colab/forward.env" ]] || fail "state file not removed"
kill -0 "$sleep_pid" 2>/dev/null && fail "forward pid still alive" || true
grep -q "stopped.*-s eos" "$STUB_STATE/calls" || fail "created session not stopped"

echo "colab scripts ok"
