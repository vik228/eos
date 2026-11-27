#!/usr/bin/env bash
# colab-drive-mount: poll-based Drive mount, no TTY. All colab_cli pieces are
# stubbed via PYTHONPATH; no network, no spend. Covers: already mounted,
# grant flow with reply, timeout, unreachable endpoint.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp="$(mktemp -d)"
tmp="$(cd "$tmp" && pwd -P)"
trap 'rm -rf "$tmp"' EXIT

fail() { echo "FAIL: $*" >&2; exit 1; }

export STUB_STATE="$tmp/stubstate"
mkdir -p "$STUB_STATE"

# Stub colab-drive status: first call absent (1), later calls mounted (0),
# unless status-code pins an exit code.
cat >"$tmp/colab-drive" <<'STUB'
#!/usr/bin/env bash
if [[ -f "${STUB_STATE:?}/status-code" ]]; then
  code="$(cat "$STUB_STATE/status-code")"
  echo "stub drive status $code"
  exit "$code"
fi
calls="${STUB_STATE:?}/status-calls"
n=0
[[ -f "$calls" ]] && n="$(cat "$calls")"
echo $((n + 1)) >"$calls"
if [[ "$n" == 0 ]]; then echo "stub drive absent"; exit 1; fi
echo "stub drive mounted"
exit 0
STUB
chmod +x "$tmp/colab-drive"
rm -f "$tmp/colab-drive-mounted"

# Stub colab_cli package shadowing the real one via PYTHONPATH.
mkdir -p "$tmp/py/colab_cli/common"
touch "$tmp/py/colab_cli/__init__.py" "$tmp/py/colab_cli/common/__init__.py"
cat >"$tmp/py/colab_cli/utils.py" <<'STUB'
def get_status_code(resp):
    return getattr(resp, "status_code", 200)
STUB
cat >"$tmp/py/colab_cli/auth.py" <<'STUB'
import json
import os

STATE = os.environ["STUB_STATE"]

class FakeResponse:
    def __init__(self, code, text):
        self.status_code = code
        self.text = text

class FakeCreds:
    def request(self, method, url, params=None, headers=None, files=None):
        mode = open(os.path.join(STATE, "creds-mode")).read().strip() if os.path.exists(os.path.join(STATE, "creds-mode")) else "grant-now"
        if mode == "raise":
            raise ConnectionError("stub network down")
        if method == "GET":
            # Mirrors reality: the dryrun GET carries only the token.
            return FakeResponse(200, "ok\n" + json.dumps({"token": "stub-token"}))
        # POST is always a propagation attempt (dryrun=false).
        n = 0
        counter = os.path.join(STATE, "post-count")
        if os.path.exists(counter):
            n = int(open(counter).read().strip() or 0)
        open(counter, "w").write(str(n + 1))
        after = int(open(os.path.join(STATE, "grant-after")).read().strip())
        if n < after:
            body = {"success": False, "unauthorized_redirect_uri": "https://stub-consent/grant"}
        else:
            body = {"success": True, "token": "stub-token"}
        return FakeResponse(200, "ok\n" + json.dumps(body))

def get_credentials(config_path=None, provider=None):
    return FakeCreds()
STUB
cat >"$tmp/py/colab_cli/common/state.py" <<'STUB'
class _Client:
    colab_domain = "https://stub-colab"

class _History:
    def log_event(self, *a, **k):
        pass

client = _Client()
client_oauth_config = "/stub/oauth.json"
auth_provider = "oauth2"
history = _History()

class _Session:
    url = "https://stub-session"
    token = "stub-session-token"
    name = "eos"
    endpoint = "stub-endpoint"

def resolve_session(name=None):
    return name or "eos"

def get_session(name):
    return _Session()
STUB
cat >"$tmp/py/colab_cli/runtime.py" <<'STUB'
import json
import os

STATE = os.environ["STUB_STATE"]

class _StdinChannel:
    def send(self, reply):
        with open(os.path.join(STATE, "stdin-reply"), "w") as fh:
            json.dump(reply, fh)

class _SessionMsg:
    def msg(self, kind, content):
        return {"kind": kind, "content": content}

class _WsClient:
    def __init__(self):
        self.session = _SessionMsg()
        self.stdin_channel = _StdinChannel()

class ColabRuntime:
    def __init__(self, url, token, session_name=None, history=None):
        self.colab_request_hook = None

    def execute_code(self, code, allow_stdin=False, timeout=None):
        assert "drive.mount" in code, "expected drive.mount code"
        msg = {
            "content": {"request": {"authType": "dfs_ephemeral"}},
            "metadata": {"colab_msg_id": 7},
        }
        hooked = self.colab_request_hook(msg, _WsClient())
        with open(os.path.join(STATE, "hook-result"), "w") as fh:
            fh.write("replied" if hooked else "ignored")

    def stop(self):
        pass
STUB
cat >"$tmp/py/colab_cli/contents.py" <<'STUB'
STUB
touch "$tmp/py/colab_cli/contents.py"

export PYTHONPATH="$tmp/py"
export EOS_COLAB_DRIVE_BIN="$tmp/colab-drive"
export EOS_COLAB_SESSION=eos EOS_COLAB_NO_OPEN=1
script="$ROOT/scripts/colab-drive-mount"

# 1. already mounted: no runtime needed, exit 0.
printf '0' >"$STUB_STATE/status-code"
out="$("$script" 2>&1)" || fail "mounted case exited $?: $out"
[[ "$out" == *"already mounted"* ]] || fail "no already-mounted message: $out"

# 2. grant flow: first dryrun unauthorized, second granted; reply sent.
rm -f "$STUB_STATE/status-code" "$STUB_STATE/status-calls"
printf '1' >"$STUB_STATE/grant-after"
rm -f "$STUB_STATE/get-count" "$STUB_STATE/post-calls" "$STUB_STATE/stdin-reply" "$STUB_STATE/hook-result"
out="$("$script" --timeout 30 --poll 1 2>&1)"
code=$?
[[ "$out" == *"CONSENT-URL: https://stub-consent/grant"* ]] || fail "no consent URL: $out"
[[ -f "$STUB_STATE/stdin-reply" ]] || fail "no input_reply sent"
grep -q '"colab_msg_id": 7' "$STUB_STATE/stdin-reply" || fail "reply missing msg id: $(cat "$STUB_STATE/stdin-reply")"
grep -q '"kind": "input_reply"' "$STUB_STATE/stdin-reply" || fail "wrong reply kind"
[[ "$code" == 0 ]] || fail "grant flow exited $code: $out"
[[ "$out" == *"mounted at /content/drive"* ]] || fail "no mounted message: $out"
rm -f "$STUB_STATE/stdin-reply"

# 3. timeout: grant never arrives within the deadline.
printf '1' >"$STUB_STATE/status-code"
printf '50' >"$STUB_STATE/grant-after"
rm -f "$STUB_STATE/get-count"
set +e
out="$("$script" --timeout 3 --poll 1 2>&1)"
code=$?
set -e
[[ "$code" == 1 ]] || fail "timeout exited $code, want 1: $out"
[[ "$out" == *"not granted in time"* ]] || fail "no timeout message: $out"
[[ ! -f "$STUB_STATE/stdin-reply" ]] || fail "reply sent despite timeout"

# 4. unreachable credentials endpoint.
printf 'raise' >"$STUB_STATE/creds-mode"
set +e
out="$("$script" --timeout 3 --poll 1 2>&1)"
code=$?
set -e
[[ "$code" == 1 ]] || fail "unreachable exited $code, want 1: $out"
[[ "$out" == *"unreachable"* ]] || fail "no unreachable message: $out"
rm -f "$STUB_STATE/creds-mode"

# 5. usage errors.
"$script" --bogus >/dev/null 2>&1 && fail "bad flag accepted"
[[ "$("$script" --help)" == *"CONSENT-URL"* ]] || fail "help text wrong"

echo "colab drive mount ok"
