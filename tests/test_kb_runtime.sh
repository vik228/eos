#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmpdir="$(mktemp -d)"
runtime_tmp="$(mktemp -d /tmp/eos-kb-runtime.XXXXXX)"
cleanup_test_runtime() {
  rm -rf "$tmpdir"
  rm -rf "$runtime_tmp"
}
trap cleanup_test_runtime EXIT

make_argument_capturing_python() {
  local path="$1"
  mkdir -p "$(dirname "$path")"
  printf '%s\n' \
    '#!/usr/bin/env bash' \
    'set -euo pipefail' \
    'printf '\''%s\n'\'' "$@" >"${CAPTURE_FILE:?}"' >"$path"
  chmod +x "$path"
}

make_versioned_python() {
  local path="$1"
  local version="$2"
  local cli_output="${3:-usage: kb [commands]}"
  mkdir -p "$(dirname "$path")"
  printf '%s\n' \
    '#!/usr/bin/env bash' \
    'set -euo pipefail' \
    'printf '\''%s\n'\'' "$*" >>"${FAKE_PYTHON_LOG:?}"' \
    'if [[ "${1:-}" == "-c" && "${2:-}" == *"sys.version_info"* ]]; then' \
    "  printf '%s\\n' '$version'" \
    '  exit 0' \
    'fi' \
    'if [[ "${1:-}" == "-c" && "${2:-}" == *"import eos_kb"* ]]; then' \
    '  exit 0' \
    'fi' \
    'if [[ "${1:-}" == "-m" && "${2:-}" == "eos_kb.cli" && "${3:-}" == "--help" ]]; then' \
    "  echo '$cli_output'" \
    '  exit 0' \
    'fi' \
    'exit 0' >"$path"
  chmod +x "$path"
}

make_fake_mv() {
  local path="$1"
  mkdir -p "$(dirname "$path")"
  printf '%s\n' \
    '#!/usr/bin/env bash' \
    'set -euo pipefail' \
    'if [[ "${FAKE_ACTIVATION_FAIL:-}" == "1" && "$*" == *".venv.next."* ]]; then exit 76; fi' \
    'exec /bin/mv "$@"' >"$path"
  chmod +x "$path"
}

make_fake_readlink() {
  local path="$1"
  mkdir -p "$(dirname "$path")"
  printf '%s\n' \
    '#!/usr/bin/env bash' \
    'set -euo pipefail' \
    'target="${!#}"' \
    'actual="$(/usr/bin/readlink "$@")"' \
    'if [[ "${FAKE_POST_ACTIVATION_FAIL:-}" == "1" && "$target" == */.venv && -L "$target" ]]; then' \
    '  if [[ -z "${FAKE_PREVIOUS_TARGET:-}" || "$actual" != "$FAKE_PREVIOUS_TARGET" ]]; then' \
    '    echo "invalid-release-target"' \
    '    exit 0' \
    '  fi' \
    'fi' \
    'printf '\''%s\n'\'' "$actual"' >"$path"
  chmod +x "$path"
}

make_fake_console_template() {
  local path="$1"
  printf '%s\n' \
    '#!PYTHON_PATH' \
    'from eos_kb.cli import main' \
    'raise SystemExit(main())' >"$path"
}

make_fake_package_templates() {
  local package_dir="$1"
  mkdir -p "$package_dir"
  : >"$package_dir/__init__.py"
  printf '%s\n' \
    'import os' \
    'import sys' \
    'if os.environ.get("FAKE_RUNTIME_FAIL") == "import":' \
    '    raise ImportError("forced import failure")' \
    'def main():' \
    '    if os.environ.get("FAKE_RUNTIME_FAIL") == "module-help" and sys.argv[0].endswith("cli.py"):' \
    '        return 74' \
    '    if os.environ.get("FAKE_RUNTIME_FAIL") == "console-help" and sys.argv[0].endswith("/kb"):' \
    '        return 75' \
    '    print("usage: kb [commands]")' \
    '    return 0' \
    'if __name__ == "__main__":' \
    '    raise SystemExit(main())' >"$package_dir/cli.py"
}

make_release_fake_uv() {
  local path="$1"
  mkdir -p "$(dirname "$path")"
  printf '%s\n' \
    '#!/usr/bin/env bash' \
    'set -euo pipefail' \
    'printf '\''env=%s %s\n'\'' "${UV_PROJECT_ENVIRONMENT:-}" "$*" >>"${FAKE_UV_LOG:?}"' \
    'if [[ "${FAKE_UV_FAIL:-}" == "${1:-}" ]]; then exit 71; fi' \
    'case "${1:-}" in' \
    '  venv)' \
    '    venv="${!#}"' \
    '    "${FAKE_REAL_PYTHON:?}" -m venv "$venv"' \
    '    ;;' \
    '  sync)' \
    '    mkdir -p "${UV_PROJECT_ENVIRONMENT:?}"' \
    '    : >"$UV_PROJECT_ENVIRONMENT/sync-marker"' \
    '    ;;' \
    '  build)' \
    '    shift; out_dir=""' \
    '    while (($#)); do' \
    '      if [[ "$1" == "--out-dir" ]]; then out_dir="$2"; break; fi' \
    '      shift' \
    '    done' \
    '    mkdir -p "$out_dir"' \
    '    : >"$out_dir/eos_kb-0.1.0-py3-none-any.whl"' \
    '    ;;' \
    '  pip)' \
    '    if [[ "${FAKE_UV_FAIL:-}" == "install" ]]; then exit 72; fi' \
    '    shift; python=""' \
    '    while (($#)); do' \
    '      if [[ "$1" == "--python" ]]; then python="$2"; break; fi' \
    '      shift' \
    '    done' \
    '    site_dir="$("$python" -c '\''import site; print(site.getsitepackages()[0])'\'')"' \
    '    mkdir -p "$site_dir/eos_kb"' \
    '    cp "${FAKE_PACKAGE_TEMPLATE:?}/__init__.py" "${FAKE_PACKAGE_TEMPLATE:?}/cli.py" "$site_dir/eos_kb/"' \
    '    { printf '\''#!%s\n'\'' "$python"; tail -n +2 "${FAKE_CONSOLE_TEMPLATE:?}"; } >"$(dirname "$python")/kb"' \
    '    chmod +x "$(dirname "$python")/kb"' \
    '    ;;' \
    '  *) exit 1 ;;' \
    'esac' >"$path"
  chmod +x "$path"
}

[[ -x "$ROOT/scripts/kb" ]] || { echo "missing executable: $ROOT/scripts/kb"; exit 1; }
[[ -x "$ROOT/scripts/setup-kb" ]] || { echo "missing executable: $ROOT/scripts/setup-kb"; exit 1; }
[[ -f "$ROOT/kb/uv.lock" ]] || { echo "missing lockfile: $ROOT/kb/uv.lock"; exit 1; }
bash -n "$ROOT/scripts/kb"
bash -n "$ROOT/scripts/setup-kb"

capture_file="$tmpdir/forwarded-arguments"
expected_file="$tmpdir/expected-arguments"
override_python="$tmpdir/override/python"
make_argument_capturing_python "$override_python"
CAPTURE_FILE="$capture_file" EOS_KB_PYTHON="$override_python" \
  "$ROOT/scripts/kb" search "query with spaces" --project 'literal*?[x]' \
  --type 'decision;$(not-executed)' --json
printf '%s\n' \
  -m \
  eos_kb.cli \
  search \
  "query with spaces" \
  --project \
  'literal*?[x]' \
  --type \
  'decision;$(not-executed)' \
  --json >"$expected_file"
cmp "$expected_file" "$capture_file"

fake_home="$tmpdir/home"
default_python="$fake_home/.local/share/eos/kb/.venv/bin/python"
make_argument_capturing_python "$default_python"
CAPTURE_FILE="$capture_file" env -u EOS_KB_PYTHON -u EOS_KB_HOME \
  HOME="$fake_home" "$ROOT/scripts/kb" status
printf '%s\n' -m eos_kb.cli status >"$expected_file"
cmp "$expected_file" "$capture_file"

set +e
setup_error="$(
  env -u EOS_KB_PYTHON -u EOS_KB_HOME HOME="$tmpdir/missing" \
    "$ROOT/scripts/kb" --help 2>&1
)"
setup_status=$?
set -e
[[ $setup_status -eq 1 ]]
[[ "$setup_error" == "EOS KB runtime is not installed. Run: $ROOT/scripts/setup-kb" ]]

broken_python="$tmpdir/broken-import/python"
mkdir -p "$(dirname "$broken_python")"
printf '%s\n' \
  '#!/usr/bin/env bash' \
  'if [[ "${1:-}" == "-c" ]]; then exit 1; fi' \
  'echo "ModuleNotFoundError: No module named eos_kb" >&2' \
  'exit 1' >"$broken_python"
chmod +x "$broken_python"
set +e
broken_import_error="$(EOS_KB_PYTHON="$broken_python" "$ROOT/scripts/kb" --help 2>&1)"
broken_import_status=$?
set -e
[[ $broken_import_status -eq 1 ]]
[[ "$broken_import_error" == "EOS KB runtime is not installed or is broken. Run: $ROOT/scripts/setup-kb" ]]

missing_cli_python="$tmpdir/missing-cli-module/python"
mkdir -p "$(dirname "$missing_cli_python")"
printf '%s\n' \
  '#!/usr/bin/env bash' \
  'if [[ "${1:-}" == "-c" && "${2:-}" == "import eos_kb" ]]; then exit 0; fi' \
  'echo "ModuleNotFoundError: No module named eos_kb.cli" >&2' \
  'exit 1' >"$missing_cli_python"
chmod +x "$missing_cli_python"
set +e
missing_cli_error="$(EOS_KB_PYTHON="$missing_cli_python" "$ROOT/scripts/kb" --help 2>&1)"
missing_cli_status=$?
set -e
[[ $missing_cli_status -eq 1 ]]
[[ "$missing_cli_error" == "EOS KB runtime is not installed or is broken. Run: $ROOT/scripts/setup-kb" ]]

set +e
missing_uv_error="$(PATH="/usr/bin:/bin" EOS_KB_HOME="$tmpdir/no-uv" "$ROOT/scripts/setup-kb" 2>&1)"
missing_uv_status=$?
set -e
[[ $missing_uv_status -eq 1 ]]
[[ "$missing_uv_error" == "uv is required. Install uv, then rerun: $ROOT/scripts/setup-kb" ]]

fake_bin="$tmpdir/fake-bin"
fake_uv_log="$tmpdir/fake-uv.log"
fake_python_log="$tmpdir/fake-python.log"
fake_console_template="$tmpdir/fake-console-template"
fake_package_template="$tmpdir/fake-package-template"
make_fake_console_template "$fake_console_template"
make_fake_package_templates "$fake_package_template"
make_release_fake_uv "$fake_bin/uv"
make_fake_mv "$fake_bin/mv"
make_fake_readlink "$fake_bin/readlink"
export FAKE_UV_LOG="$fake_uv_log"
export FAKE_PYTHON_LOG="$fake_python_log"
export FAKE_CONSOLE_TEMPLATE="$fake_console_template"
export FAKE_PACKAGE_TEMPLATE="$fake_package_template"
export FAKE_REAL_PYTHON="$(command -v python3)"

runtime_home="$runtime_tmp/runtime"
PATH="$fake_bin:/usr/bin:/bin" EOS_KB_HOME="$runtime_home" "$ROOT/scripts/setup-kb"
first_target="$(readlink "$runtime_home/.venv")"
first_release="$(dirname "$runtime_home/$first_target")"
PATH="$fake_bin:/usr/bin:/bin" EOS_KB_HOME="$runtime_home" "$ROOT/scripts/setup-kb"
second_target="$(readlink "$runtime_home/.venv")"
second_release="$(dirname "$runtime_home/$second_target")"
[[ -d "$first_release" ]]
PATH="$fake_bin:/usr/bin:/bin" EOS_KB_HOME="$runtime_home" "$ROOT/scripts/setup-kb"
third_target="$(readlink "$runtime_home/.venv")"
resolved_venv="$(cd "$runtime_home/.venv" && pwd -P)"
resolved_runtime_home="$(cd "$runtime_home" && pwd -P)"
installed_venv="$(cat "$runtime_home/.venv/.eos-kb-release")"
runtime_version="$(
  "$runtime_home/.venv/bin/python" -c \
    'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")'
)"
[[ "$runtime_version" == "3.12" ]]
[[ -L "$runtime_home/.venv" ]]
[[ "$third_target" == releases/release.*'/.venv' ]]
[[ "$resolved_venv" == "$resolved_runtime_home"/releases/release.*/.venv ]]
[[ "$installed_venv" == "$runtime_home"/releases/release.*/.venv ]]
[[ "$(head -1 "$runtime_home/.venv/bin/kb")" == "#!$installed_venv/bin/python" ]]
"$runtime_home/.venv/bin/python" -c 'import eos_kb.cli'
"$runtime_home/.venv/bin/python" -m eos_kb.cli --help >/dev/null
"$runtime_home/.venv/bin/kb" --help >/dev/null
EOS_KB_HOME="$runtime_home" "$ROOT/scripts/kb" --help >/dev/null
[[ "$(find "$runtime_home/releases" -mindepth 1 -maxdepth 1 -type d | wc -l | tr -d ' ')" -eq 2 ]]
[[ ! -e "$first_release" ]]
[[ -d "$second_release" ]]
[[ "$(grep -c ' venv ' "$fake_uv_log")" -eq 3 ]]
[[ "$(grep -c ' sync ' "$fake_uv_log")" -eq 3 ]]
[[ "$(grep -c ' build ' "$fake_uv_log")" -eq 3 ]]
[[ "$(grep -c ' pip install ' "$fake_uv_log")" -eq 3 ]]
! grep -Fq "$ROOT/kb" "$fake_uv_log"
first_build_line="$(grep -n ' build ' "$fake_uv_log" | head -1 | cut -d: -f1)"
first_venv_line="$(grep -n ' venv ' "$fake_uv_log" | head -1 | cut -d: -f1)"
[[ "$first_build_line" -lt "$first_venv_line" ]]
! grep -Fq "env=$runtime_home/.venv sync " "$fake_uv_log"

stale_home="$runtime_tmp/stale-runtime"
make_versioned_python "$stale_home/.venv/bin/python" "3.11"
: >"$fake_uv_log"
PATH="$fake_bin:/usr/bin:/bin" EOS_KB_HOME="$stale_home" "$ROOT/scripts/setup-kb"
[[ -L "$stale_home/.venv" ]]
grep -Eq "venv .*${stale_home}/releases/release\\.[^/]+/\\.venv$" "$fake_uv_log"

corrupt_home="$runtime_tmp/corrupt-runtime"
mkdir -p "$corrupt_home/.venv/bin"
printf '%s\n' '#!/usr/bin/env bash' 'exit 42' >"$corrupt_home/.venv/bin/python"
chmod +x "$corrupt_home/.venv/bin/python"
: >"$fake_uv_log"
PATH="$fake_bin:/usr/bin:/bin" EOS_KB_HOME="$corrupt_home" "$ROOT/scripts/setup-kb"
EOS_KB_HOME="$corrupt_home" "$ROOT/scripts/kb" --help >/dev/null

assert_failed_setup_preserves_prior() {
  local stage="$1"
  local failure_source="$2"
  local failed_home="$runtime_tmp/failed-$stage-runtime"
  local setup_status

  make_versioned_python "$failed_home/.venv/bin/python" "3.12" "prior-runtime"
  : >"$fake_uv_log"
  set +e
  case "$failure_source" in
    uv)
      PATH="$fake_bin:/usr/bin:/bin" FAKE_UV_FAIL="$stage" EOS_KB_HOME="$failed_home" \
        "$ROOT/scripts/setup-kb" >"$tmpdir/failed-$stage.log" 2>&1
      ;;
    runtime)
      PATH="$fake_bin:/usr/bin:/bin" FAKE_RUNTIME_FAIL="$stage" EOS_KB_HOME="$failed_home" \
        "$ROOT/scripts/setup-kb" >"$tmpdir/failed-$stage.log" 2>&1
      ;;
    activation)
      PATH="$fake_bin:/usr/bin:/bin" FAKE_ACTIVATION_FAIL=1 EOS_KB_HOME="$failed_home" \
        "$ROOT/scripts/setup-kb" >"$tmpdir/failed-$stage.log" 2>&1
      ;;
    post-activation)
      PATH="$fake_bin:/usr/bin:/bin" FAKE_POST_ACTIVATION_FAIL=1 EOS_KB_HOME="$failed_home" \
        "$ROOT/scripts/setup-kb" >"$tmpdir/failed-$stage.log" 2>&1
      ;;
  esac
  setup_status=$?
  set -e

  [[ $setup_status -ne 0 ]] || { echo "$stage unexpectedly succeeded"; return 1; }
  [[ ! -L "$failed_home/.venv" ]] || { echo "$stage left the candidate active"; return 1; }
  [[ "$(EOS_KB_HOME="$failed_home" "$ROOT/scripts/kb" --help)" == "prior-runtime" ]] || {
    echo "$stage did not preserve the prior CLI"
    return 1
  }
  ! find "$failed_home" -maxdepth 1 \( -name '.venv.next.*' -o -name '.venv.backup.*' \) | grep -q . || {
    echo "$stage left activation artifacts"
    return 1
  }
  if [[ -d "$failed_home/releases" ]]; then
    ! find "$failed_home/releases" -mindepth 1 -maxdepth 1 -type d | grep -q . || {
      echo "$stage left a failed release"
      return 1
    }
  fi
}

assert_failed_setup_preserves_prior build uv
assert_failed_setup_preserves_prior sync uv
assert_failed_setup_preserves_prior install uv
assert_failed_setup_preserves_prior import runtime
assert_failed_setup_preserves_prior module-help runtime
assert_failed_setup_preserves_prior console-help runtime
assert_failed_setup_preserves_prior activation activation
assert_failed_setup_preserves_prior post-activation post-activation

rollback_home="$runtime_tmp/symlink-rollback-runtime"
PATH="$fake_bin:/usr/bin:/bin" EOS_KB_HOME="$rollback_home" "$ROOT/scripts/setup-kb" >/dev/null
prior_target="$(readlink "$rollback_home/.venv")"
set +e
PATH="$fake_bin:/usr/bin:/bin" FAKE_POST_ACTIVATION_FAIL=1 FAKE_PREVIOUS_TARGET="$prior_target" EOS_KB_HOME="$rollback_home" \
  "$ROOT/scripts/setup-kb" >"$tmpdir/failed-symlink-rollback.log" 2>&1
rollback_status=$?
set -e
[[ $rollback_status -ne 0 ]]
[[ "$(readlink "$rollback_home/.venv")" == "$prior_target" ]]
EOS_KB_HOME="$rollback_home" "$ROOT/scripts/kb" --help >/dev/null
[[ "$(find "$rollback_home/releases" -mindepth 1 -maxdepth 1 -type d | wc -l | tr -d ' ')" -eq 1 ]]

grep -Fq 'setuptools==' "$ROOT/kb/pyproject.toml"
grep -Fq 'uv sync --locked --no-dev --no-install-project' "$ROOT/scripts/setup-kb"
grep -Fq 'kb/.venv/' "$ROOT/.gitignore"
grep -Fq 'kb/.pytest_cache/' "$ROOT/.gitignore"
grep -Fq 'kb/**/__pycache__/' "$ROOT/.gitignore"
grep -Fq 'kb/build/' "$ROOT/.gitignore"
grep -Fq 'kb/src/*.egg-info/' "$ROOT/.gitignore"

if command -v uv >/dev/null 2>&1; then
  real_runtime="$runtime_tmp/real-runtime"
  status_before="$(git -C "$ROOT" status --porcelain --untracked-files=all)"
  if UV_OFFLINE=1 EOS_KB_HOME="$real_runtime" \
    "$ROOT/scripts/setup-kb" >"$tmpdir/real-setup.log" 2>&1; then
    [[ -L "$real_runtime/.venv" ]]
    real_resolved_venv="$(cd "$real_runtime/.venv" && pwd -P)"
    real_resolved_runtime="$(cd "$real_runtime" && pwd -P)"
    real_installed_venv="$(cat "$real_runtime/.venv/.eos-kb-release")"
    [[ "$real_resolved_venv" == "$real_resolved_runtime"/releases/release.*/.venv ]]
    [[ "$(head -1 "$real_runtime/.venv/bin/kb")" == "#!$real_installed_venv/bin/python" ]]
    "$real_runtime/.venv/bin/python" -c 'import eos_kb.cli'
    "$real_runtime/.venv/bin/python" -m eos_kb.cli --help >/dev/null
    "$real_runtime/.venv/bin/kb" --help >/dev/null
    installed_home="$runtime_tmp/installed-home"
    installed_kb="$runtime_tmp/installed-knowledge"
    mkdir -p "$installed_home" "$installed_kb"
    HOME="$installed_home" "$real_runtime/.venv/bin/kb" session start \
      --kb "$installed_kb" --cwd "$installed_kb" --agent test \
      --profile installed-runtime --json >/dev/null
    EOS_KB_HOME="$real_runtime" "$ROOT/scripts/kb" --help >/dev/null
    UV_OFFLINE=1 EOS_KB_HOME="$real_runtime" "$ROOT/scripts/setup-kb" >/dev/null
    [[ -L "$real_runtime/.venv" ]]
    "$real_runtime/.venv/bin/python" -c 'import eos_kb.cli'
    "$real_runtime/.venv/bin/python" -m eos_kb.cli --help >/dev/null
    "$real_runtime/.venv/bin/kb" --help >/dev/null
    [[ "$(find "$real_runtime/releases" -mindepth 1 -maxdepth 1 -type d | wc -l | tr -d ' ')" -eq 2 ]]
    status_after="$(git -C "$ROOT" status --porcelain --untracked-files=all)"
    [[ "$status_after" == "$status_before" ]]
  else
    real_setup_status=$?
    if grep -Fq "Failed to initialize cache at \`$HOME/.cache/uv\`" \
      "$tmpdir/real-setup.log" && \
      grep -Fq 'Operation not permitted (os error 1)' "$tmpdir/real-setup.log"; then
      echo "real kb installer smoke skipped: sandbox cannot access $HOME/.cache/uv"
    elif grep -Eiq \
      'not found in (the )?cache|offline[^[:cntrl:]]*(cache|unavailable)|network connectivity is disabled' \
      "$tmpdir/real-setup.log"; then
      echo "real kb installer smoke skipped: locked artifacts unavailable offline"
    else
      cat "$tmpdir/real-setup.log" >&2
      exit "$real_setup_status"
    fi
  fi
fi

echo "kb runtime and installer ok"
