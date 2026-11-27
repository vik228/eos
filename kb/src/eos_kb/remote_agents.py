"""Remote coding-agent session launcher and monitor for EOS MCP."""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

ALLOWED_AGENTS_BY_PROFILE: dict[str, frozenset[str]] = {
    "work": frozenset({"claude"}),
    "personal": frozenset({"claude", "codex", "gemini", "opencode"}),
}

_SLUG_RE = re.compile(r"[^a-z0-9]+")


class RemoteAgentError(ValueError):
    """Validation, isolation, or lifecycle error for remote agent sessions."""


def _eos_root() -> Path:
    return Path(os.environ.get("EOS_ROOT", str(Path.home() / "personal/eos"))).expanduser().resolve()


def _profile_workspace_root(profile: str) -> Path:
    home = Path(os.environ.get("HOME", str(Path.home())))
    if profile == "work":
        return Path(os.environ.get("EOS_WORK_ROOT", str(home / "work"))).expanduser().resolve()
    if profile == "personal":
        return Path(os.environ.get("EOS_PERSONAL_ROOT", str(home / "personal"))).expanduser().resolve()
    raise RemoteAgentError(f"Unsupported profile: {profile}")


def _runs_root(profile: str) -> Path:
    home = Path(os.environ.get("HOME", str(Path.home())))
    base = Path(
        os.environ.get("EOS_REMOTE_AGENTS_DIR", str(home / ".local/share/eos/kb/remote-agents"))
    ).expanduser()
    path = base / profile
    path.mkdir(parents=True, exist_ok=True)
    return path


def _resolve_cwd(profile: str, cwd: str) -> Path:
    if not cwd or not cwd.strip():
        raise RemoteAgentError("cwd must be a non-empty directory inside the profile workspace.")
    ws_root = _profile_workspace_root(profile)
    raw = Path(cwd.strip()).expanduser()
    candidate = raw.resolve() if raw.is_absolute() else (ws_root / raw).resolve()
    if candidate != ws_root and not candidate.is_relative_to(ws_root):
        raise RemoteAgentError(f"cwd '{cwd}' is outside the '{profile}' workspace root ({ws_root}).")
    if not candidate.is_dir():
        raise RemoteAgentError(f"cwd does not exist or is not a directory: {candidate}")
    return candidate


def _pid_alive(pid: int | None) -> bool:
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def _slugify(value: str) -> str:
    return _SLUG_RE.sub("-", value.lower()).strip("-")[:32] or "session"


def _read_meta(run_dir: Path) -> dict[str, Any]:
    meta_path = run_dir / "meta.json"
    if not meta_path.is_file():
        raise RemoteAgentError(f"Unknown run_id: {run_dir.name}")
    return json.loads(meta_path.read_text(encoding="utf-8"))


def _write_meta(run_dir: Path, meta: dict[str, Any]) -> None:
    meta_path = run_dir / "meta.json"
    tmp = meta_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, meta_path)


def _build_agent_command(
    *,
    profile: str,
    agent: str,
    name: str,
    session_id: str,
    prompt: str,
    resume: bool = False,
    permission_mode: str | None = None,
) -> tuple[list[str], dict[str, str], str]:
    root = _eos_root()
    extra_env: dict[str, str] = {}
    if agent == "claude":
        script = root / "scripts" / f"claude-{profile}"
        if permission_mode:
            extra_env["CLAUDE_PERMISSION_MODE"] = permission_mode
        if resume:
            cmd = [
                str(script),
                "--resume",
                session_id,
                "-p",
                prompt,
                "--output-format",
                "stream-json",
                "--verbose",
            ]
        else:
            cmd = [
                str(script),
                "-n",
                name,
                "--session-id",
                session_id,
                "-p",
                prompt,
                "--output-format",
                "stream-json",
                "--verbose",
            ]
        resume_cmd = f"claude-{profile} --resume {session_id}"
        return cmd, extra_env, resume_cmd

    if profile != "personal":
        raise RemoteAgentError(f"Agent '{agent}' is only allowed on the personal profile.")

    if agent == "codex":
        script = root / "scripts" / "codex-personal"
        return [str(script), "exec", prompt], extra_env, f"codex-personal"
    if agent == "gemini":
        script = root / "scripts" / "gemini-eos"
        return [str(script), "-p", prompt], extra_env, "gemini-eos"
    if agent == "opencode":
        script = root / "scripts" / "opencode-personal"
        return [str(script), "run", prompt], extra_env, "opencode-personal"
    raise RemoteAgentError(f"Unsupported agent: {agent}")


def _parse_claude_stream_events(log_path: Path, max_entries: int = 40) -> tuple[list[str], str | None]:
    if not log_path.is_file():
        return [], None
    lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    entries: list[str] = []
    final_result: str | None = None
    for raw in lines:
        raw_s = raw.strip()
        if not raw_s:
            continue
        if not raw_s.startswith("{"):
            entries.append(raw_s[:300])
            continue
        try:
            ev = json.loads(raw_s)
        except json.JSONDecodeError:
            entries.append(raw_s[:300])
            continue
        ev_type = ev.get("type")
        if ev_type == "assistant":
            msg = ev.get("message") or {}
            for block in msg.get("content") or []:
                if not isinstance(block, dict):
                    continue
                btype = block.get("type")
                if btype == "text" and block.get("text"):
                    text = " ".join(str(block["text"]).split())
                    entries.append(f"[assistant] {text[:350]}")
                elif btype == "tool_use":
                    tname = block.get("name", "tool")
                    tinput = block.get("input") or {}
                    brief_in = json.dumps(tinput, ensure_ascii=False)[:140]
                    entries.append(f"[tool:{tname}] {brief_in}")
        elif ev_type == "result":
            res_text = ev.get("result")
            if isinstance(res_text, str) and res_text.strip():
                final_result = res_text.strip()
                entries.append(f"[result] {' '.join(final_result.split())[:400]}")
        elif ev_type == "system" and ev.get("subtype") == "init":
            model = ev.get("model") or ""
            entries.append(f"[init] session={ev.get('session_id', '')} model={model}")
    return entries[-max_entries:], final_result


def _sync_live_state(run_dir: Path) -> dict[str, Any]:
    meta = _read_meta(run_dir)
    if meta.get("status") == "running" and not _pid_alive(meta.get("pid")):
        exit_file = run_dir / "exit_code"
        if exit_file.is_file():
            try:
                code = int(exit_file.read_text(encoding="utf-8").strip())
            except ValueError:
                code = -1
            meta["exit_code"] = code
            meta["status"] = "completed" if code == 0 else "failed"
        else:
            meta["status"] = "exited"
        meta["ended_at"] = meta.get("ended_at") or _now_iso()
        _write_meta(run_dir, meta)
    return meta


def start_remote_agent(
    profile: str,
    *,
    name: str,
    prompt: str,
    cwd: str,
    agent: str = "claude",
    permission_mode: str | None = None,
    command_override: list[str] | None = None,
) -> dict[str, Any]:
    agent_clean = (agent or "claude").strip().lower()
    allowed = ALLOWED_AGENTS_BY_PROFILE.get(profile, frozenset())
    if agent_clean not in allowed:
        raise RemoteAgentError(
            f"Agent '{agent_clean}' is not permitted on '{profile}' profile. Allowed: {', '.join(sorted(allowed))}."
        )
    name_clean = (name or "").strip()
    prompt_clean = (prompt or "").strip()
    if not name_clean:
        raise RemoteAgentError("name must be non-empty so the session can be identified later.")
    if not prompt_clean:
        raise RemoteAgentError("prompt must be non-empty.")
    resolved_cwd = _resolve_cwd(profile, cwd)

    session_id = str(uuid.uuid4())
    ts = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M%S")
    run_id = f"{ts}-{_slugify(name_clean)}-{session_id[:6]}"
    run_dir = _runs_root(profile) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    if command_override is not None:
        cmd, extra_env, resume_cmd = command_override, {}, f"{agent_clean} --resume {session_id}"
    else:
        cmd, extra_env, resume_cmd = _build_agent_command(
            profile=profile,
            agent=agent_clean,
            name=name_clean,
            session_id=session_id,
            prompt=prompt_clean,
            resume=False,
            permission_mode=permission_mode,
        )

    meta: dict[str, Any] = {
        "run_id": run_id,
        "profile": profile,
        "agent": agent_clean,
        "name": name_clean,
        "session_id": session_id,
        "cwd": str(resolved_cwd),
        "prompt": prompt_clean,
        "status": "running",
        "pid": None,
        "started_at": _now_iso(),
        "ended_at": None,
        "exit_code": None,
        "resume_command": resume_cmd,
        "turns": 1,
        "cmd": cmd,
        "extra_env": extra_env,
    }
    _write_meta(run_dir, meta)

    proc = _spawn_detached_runner(run_dir)
    meta["pid"] = proc.pid
    _write_meta(run_dir, meta)
    return meta


def _spawn_detached_runner(run_dir: Path) -> subprocess.Popen[bytes]:
    runner_err = (run_dir / "runner.log").open("ab")
    try:
        return subprocess.Popen(
            [sys.executable, "-m", "eos_kb.remote_agents", "_exec", str(run_dir)],
            stdin=subprocess.DEVNULL,
            stdout=runner_err,
            stderr=runner_err,
            start_new_session=True,
            close_fds=True,
        )
    finally:
        runner_err.close()


def followup_remote_agent(
    profile: str,
    *,
    run_id: str,
    prompt: str,
    command_override: list[str] | None = None,
) -> dict[str, Any]:
    prompt_clean = (prompt or "").strip()
    if not prompt_clean:
        raise RemoteAgentError("prompt must be non-empty.")
    run_dir = _runs_root(profile) / run_id
    meta = _sync_live_state(run_dir)
    if meta.get("agent") != "claude":
        raise RemoteAgentError("Follow-up resume is currently supported only for Claude Code sessions.")
    if meta.get("status") == "running" and _pid_alive(meta.get("pid")):
        raise RemoteAgentError(f"Run '{run_id}' is still running; wait for it to finish or stop it first.")

    if command_override is not None:
        cmd, extra_env = command_override, {}
    else:
        cmd, extra_env, _ = _build_agent_command(
            profile=profile,
            agent="claude",
            name=meta["name"],
            session_id=meta["session_id"],
            prompt=prompt_clean,
            resume=True,
        )

    exit_file = run_dir / "exit_code"
    exit_file.unlink(missing_ok=True)
    meta["cmd"] = cmd
    meta["extra_env"] = extra_env
    meta["status"] = "running"
    meta["ended_at"] = None
    meta["exit_code"] = None
    meta["turns"] = int(meta.get("turns", 1)) + 1
    meta["last_prompt"] = prompt_clean
    _write_meta(run_dir, meta)

    proc = _spawn_detached_runner(run_dir)
    meta["pid"] = proc.pid
    _write_meta(run_dir, meta)
    return meta


def list_remote_agents(profile: str, *, limit: int = 10) -> list[dict[str, Any]]:
    root = _runs_root(profile)
    runs: list[dict[str, Any]] = []
    for entry in sorted(root.iterdir(), reverse=True):
        if not entry.is_dir() or not (entry / "meta.json").is_file():
            continue
        runs.append(_sync_live_state(entry))
        if len(runs) >= max(1, min(limit, 50)):
            break
    return runs


def status_remote_agent(profile: str, *, run_id: str) -> dict[str, Any]:
    run_dir = _runs_root(profile) / run_id
    meta = _sync_live_state(run_dir)
    log_path = run_dir / "output.log"
    if meta.get("agent") == "claude":
        recent, final_result = _parse_claude_stream_events(log_path, max_entries=12)
    else:
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines() if log_path.is_file() else []
        recent = lines[-12:]
        final_result = "\n".join(lines[-20:]).strip() if lines else None
    return {**meta, "recent_events": recent, "final_result": final_result}


def logs_remote_agent(profile: str, *, run_id: str, tail_lines: int = 40) -> dict[str, Any]:
    run_dir = _runs_root(profile) / run_id
    meta = _sync_live_state(run_dir)
    log_path = run_dir / "output.log"
    tail_n = max(5, min(int(tail_lines), 200))
    if meta.get("agent") == "claude":
        entries, final_result = _parse_claude_stream_events(log_path, max_entries=tail_n)
        text = "\n".join(entries) if entries else "(no output yet)"
    else:
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines() if log_path.is_file() else []
        text = "\n".join(lines[-tail_n:]) if lines else "(no output yet)"
        final_result = None
    return {"run_id": run_id, "status": meta["status"], "name": meta["name"], "text": text, "final_result": final_result}


def stop_remote_agent(profile: str, *, run_id: str) -> dict[str, Any]:
    run_dir = _runs_root(profile) / run_id
    meta = _sync_live_state(run_dir)
    pid = meta.get("pid")
    if pid and _pid_alive(pid):
        try:
            os.killpg(pid, signal.SIGTERM)
        except OSError:
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
        for _ in range(10):
            if not _pid_alive(pid):
                break
            time.sleep(0.2)
        if _pid_alive(pid):
            try:
                os.killpg(pid, signal.SIGKILL)
            except OSError:
                pass
    meta["status"] = "stopped"
    meta["ended_at"] = _now_iso()
    _write_meta(run_dir, meta)
    return meta


def _exec_run(run_dir: Path) -> int:
    meta = _read_meta(run_dir)
    cmd = list(meta["cmd"])
    cwd = meta["cwd"]
    env = os.environ.copy()
    env.update({str(k): str(v) for k, v in (meta.get("extra_env") or {}).items()})
    env["EOS_AGENT_CWD"] = cwd
    log_path = run_dir / "output.log"
    with log_path.open("ab") as out:
        proc = subprocess.Popen(
            cmd,
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=subprocess.STDOUT,
        )
        code = proc.wait()
    (run_dir / "exit_code").write_text(f"{code}\n", encoding="utf-8")
    meta = _read_meta(run_dir)
    if meta.get("status") != "stopped":
        meta["status"] = "completed" if code == 0 else "failed"
    meta["exit_code"] = code
    meta["ended_at"] = _now_iso()
    _write_meta(run_dir, meta)
    return code


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) == 2 and args[0] == "_exec":
        return _exec_run(Path(args[1]))
    print("Usage: python -m eos_kb.remote_agents _exec <run_dir>", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
