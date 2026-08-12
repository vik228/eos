"""Workspace routing and deterministic knowledge-bundle initialization."""

from __future__ import annotations

import errno
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import yaml

from .freshness import CoverageRule
from .paths import kb_config_path
from .schema import SchemaValidationError


class RegistryError(SchemaValidationError):
    """A structured workspace registry or routing failure."""


class InitializationError(SchemaValidationError):
    """A structured bundle layout conflict."""


@dataclass(frozen=True)
class WorkspaceRoute:
    workspace: Path
    kb: Path
    project: str
    registered: bool = True
    coverage: tuple[CoverageRule, ...] = ()


@dataclass(frozen=True)
class WorkspaceRegistry:
    workspaces: dict[Path, WorkspaceRoute]


_HOME_VARIABLE = re.compile(r"\$HOME(?=$|[/\\])")


def _expand_path(value: str, *, home: Path) -> Path:
    expanded = value
    if expanded == "~" or expanded.startswith("~/"):
        expanded = str(home) + expanded[1:]
    expanded = _HOME_VARIABLE.sub(str(home), expanded)
    return Path(expanded).expanduser()


def _registry_error(code: str, filename: str, field_path: str, remediation: str) -> RegistryError:
    return RegistryError(code, filename, field_path, remediation)


def _coverage_rules(value: object, *, filename: str, field: str) -> tuple[CoverageRule, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise _registry_error(
            "registry.coverage_type", filename, field, "Set coverage to a list of rules."
        )
    rules: list[CoverageRule] = []
    for index, item in enumerate(value):
        item_field = f"{field}[{index}]"
        if not isinstance(item, dict) or set(item) - {"paths", "concepts", "ignore"}:
            raise _registry_error(
                "registry.coverage_rule", filename, item_field,
                "Use only paths, concepts, and optional ignore fields.",
            )
        paths = item.get("paths")
        concepts = item.get("concepts")
        ignore = item.get("ignore", [])
        if not (
            isinstance(paths, list)
            and paths
            and all(isinstance(entry, str) and entry.strip() for entry in paths)
            and isinstance(concepts, list)
            and concepts
            and all(isinstance(entry, str) and entry.strip() for entry in concepts)
            and isinstance(ignore, list)
            and all(isinstance(entry, str) and entry.strip() for entry in ignore)
        ):
            raise _registry_error(
                "registry.coverage_rule", filename, item_field,
                "Use non-empty string lists for paths and concepts, and a string list for ignore.",
            )
        rules.append(CoverageRule(tuple(paths), tuple(concepts), tuple(ignore)))
    return tuple(rules)


def _default_registry_path() -> Path:
    return kb_config_path("workspaces.yaml")


def load_registry(
    path: Path | None = None,
    *,
    home: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> WorkspaceRegistry:
    """Load the registry using the supplied environment, never import-time state."""

    env = dict(os.environ if environ is None else environ)
    home_path = Path(home or env.get("HOME", str(Path.home())))
    registry_path = path or Path(env.get("EOS_KB_REGISTRY", str(_default_registry_path())))
    registry_path = _expand_path(str(registry_path), home=home_path)
    try:
        payload = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise _registry_error(
            "registry.unreadable", registry_path.name, "$", f"Make the registry readable YAML: {exc}."
        ) from exc

    if not isinstance(payload, dict) or not isinstance(payload.get("workspaces"), dict):
        raise _registry_error("registry.type", registry_path.name, "$.workspaces", "Set workspaces to a path-keyed mapping.")
    if not payload["workspaces"]:
        raise _registry_error("registry.type", registry_path.name, "$.workspaces", "Define at least one workspace route.")

    work_root = env.get("EOS_WORK_KNOWLEDGE_ROOT")
    personal_root = env.get("EOS_PERSONAL_KNOWLEDGE_ROOT")
    routes: dict[Path, WorkspaceRoute] = {}
    for workspace_value, route_value in payload["workspaces"].items():
        field = f"$.workspaces.{workspace_value}"
        if not isinstance(workspace_value, str) or not workspace_value.strip():
            raise _registry_error("registry.key", registry_path.name, "$.workspaces", "Use non-empty workspace path keys.")
        if not isinstance(route_value, dict):
            raise _registry_error("registry.type", registry_path.name, field, "Set each workspace route to a mapping.")
        unsupported_keys = sorted(set(route_value) - {"kb", "project", "coverage"})
        if unsupported_keys:
            key = unsupported_keys[0]
            raise _registry_error(
                "registry.additional_property",
                registry_path.name,
                f"{field}.{key}",
                f"Remove unsupported route key '{key}'.",
            )
        if not isinstance(route_value.get("kb"), str) or not route_value["kb"].strip():
            raise _registry_error("registry.required", registry_path.name, f"{field}.kb", "Set a non-empty KB root.")
        if not isinstance(route_value.get("project"), str) or not route_value["project"].strip():
            raise _registry_error("registry.required", registry_path.name, f"{field}.project", "Set a non-empty project name.")

        workspace = _expand_path(workspace_value, home=home_path).resolve()
        kb = _expand_path(route_value["kb"], home=home_path).resolve()
        workspace_text = workspace.as_posix()
        if work_root and "/work/" in workspace_text:
            kb = _expand_path(work_root, home=home_path).resolve()
        elif personal_root and "/personal/" in workspace_text:
            kb = _expand_path(personal_root, home=home_path).resolve()
        if workspace in routes:
            raise _registry_error("registry.duplicate", registry_path.name, field, "Remove duplicate workspace routes.")
        coverage = _coverage_rules(
            route_value.get("coverage"),
            filename=registry_path.name,
            field=f"{field}.coverage",
        )
        routes[workspace] = WorkspaceRoute(
            workspace, kb, route_value["project"], coverage=coverage
        )

    return WorkspaceRegistry(routes)


def match_workspace(cwd: Path, registry: WorkspaceRegistry) -> WorkspaceRoute:
    candidate = cwd.expanduser().resolve()
    matches = [route for root, route in registry.workspaces.items() if candidate == root or root in candidate.parents]
    if not matches:
        raise _registry_error(
            "registry.workspace_not_found",
            "workspaces.yaml",
            "$.workspaces",
            f"Register a workspace covering '{candidate}'.",
        )
    return max(matches, key=lambda route: len(route.workspace.parts))


def resolve_workspace(
    cwd: Path,
    *,
    registry: WorkspaceRegistry | None = None,
    kb: Path | None = None,
    project: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> WorkspaceRoute:
    env = dict(os.environ if environ is None else environ)
    loaded = registry or load_registry(environ=env)
    if kb is None:
        route = match_workspace(cwd, loaded)
        if project is not None:
            if not project.strip():
                raise _registry_error("registry.invalid_project", "workspaces.yaml", "$.project", "Project must be a non-empty name.")
            return WorkspaceRoute(
                route.workspace,
                route.kb,
                project,
                registered=route.registered,
                coverage=route.coverage,
            )
        return route
    if project is not None and not project.strip():
        raise _registry_error("registry.invalid_project", "workspaces.yaml", "$.project", "Project must be a non-empty name.")
    home_path = Path(env.get("HOME", str(Path.home())))
    kb_path = _expand_path(str(kb), home=home_path).resolve()
    try:
        route = match_workspace(cwd, loaded)
    except RegistryError as exc:
        if exc.code != "registry.workspace_not_found":
            raise
        route = None
    if route is not None and route.kb != kb_path:
        raise _registry_error(
            "registry.kb_mismatch",
            "workspaces.yaml",
            "$.kb",
            f"Use the registered KB '{route.kb}' for workspace '{route.workspace}'.",
        )
    return WorkspaceRoute(
        route.workspace if route else cwd.expanduser().resolve(),
        kb_path,
        project or (route.project if route else "knowledge"),
        registered=route is not None,
        coverage=route.coverage if route else (),
    )


def _template(name: str) -> str:
    path = kb_config_path("templates", name)
    return path.read_text(encoding="utf-8")


def _initialization_error(relative_path: Path, expected: str) -> InitializationError:
    display = relative_path.as_posix() if relative_path.parts else "."
    return InitializationError(
        "init.layout_conflict",
        display,
        f"$.layout.{display}" if display != "." else "$.layout",
        f"Expected '{display}' to be {expected} without symlinks.",
    )


def _open_directory(root_fd: int, relative_path: Path) -> int:
    current_fd = os.dup(root_fd)
    traversed = Path()
    try:
        for component in relative_path.parts:
            traversed /= component
            try:
                os.mkdir(component, mode=0o755, dir_fd=current_fd)
            except FileExistsError:
                pass
            try:
                next_fd = os.open(
                    component,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=current_fd,
                )
            except OSError as exc:
                if exc.errno in {errno.ELOOP, errno.ENOTDIR}:
                    raise _initialization_error(traversed, "a directory") from exc
                raise
            os.close(current_fd)
            current_fd = next_fd
        return current_fd
    except BaseException:
        os.close(current_fd)
        raise


def _write_exclusive(root_fd: int, relative_path: Path, content: str) -> None:
    parent_fd = _open_directory(root_fd, relative_path.parent)
    try:
        for attempt in range(2):
            try:
                file_fd = os.open(
                    relative_path.name,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    0o644,
                    dir_fd=parent_fd,
                )
            except FileExistsError:
                try:
                    existing = os.stat(
                        relative_path.name,
                        dir_fd=parent_fd,
                        follow_symlinks=False,
                    )
                except FileNotFoundError:
                    if attempt == 0:
                        continue
                    raise
                if stat.S_ISREG(existing.st_mode):
                    return
                raise _initialization_error(relative_path, "a regular file")
            with os.fdopen(file_fd, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(content)
            return
    finally:
        os.close(parent_fd)


def initialize_bundle(root: Path, project: str) -> None:
    """Create missing bundle files without replacing any existing bytes."""

    if not isinstance(project, str) or not project.strip() or Path(project).name != project or project in {".", ".."}:
        raise _registry_error("registry.invalid_project", "workspaces.yaml", "$.project", "Project must be a non-empty name.")
    root = root.expanduser().resolve()
    try:
        root.mkdir(parents=True, exist_ok=True)
    except FileExistsError as exc:
        raise _initialization_error(Path(), "a directory") from exc

    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for directory in (
            "areas", "patterns", "logs", "inbox", "archive",
            f"projects/{project}/architecture", f"projects/{project}/invariants",
            f"projects/{project}/decisions", f"projects/{project}/runbooks",
            f"projects/{project}/failure-modes", f"projects/{project}/incidents",
            f"projects/{project}/specifications", f"projects/{project}/references",
        ):
            directory_fd = _open_directory(root_fd, Path(directory))
            os.close(directory_fd)

        index = _template("index.md")
        pending = _template("pending-index.md")
        proposal_inbox = _template("proposal-inbox.md")
        _write_exclusive(root_fd, Path("index.md"), index)
        legacy_index = index.replace("generated: true\n", "").replace(
            "title: Knowledge Index", "title: Legacy Knowledge Router"
        ).replace(
            "# Knowledge Index",
            "# Legacy Knowledge Router\n\nSee [index.md](index.md).",
        )
        _write_exclusive(root_fd, Path("00-index.md"), legacy_index)
        _write_exclusive(
            root_fd,
            Path("_pending-kb-updates.md"),
            pending.replace("PROPOSAL_INBOX_PATH", f"inbox/{project}/index.md"),
        )
        _write_exclusive(root_fd, Path("inbox") / project / "index.md", proposal_inbox)
        _write_exclusive(root_fd, Path("projects") / project / "index.md", index.replace("title: Knowledge Index", f"title: {project} Knowledge Index").replace("# Knowledge Index", f"# {project} Knowledge Index"))
        _write_exclusive(
            root_fd,
            Path("projects") / project / "_pending-kb-updates.md",
            pending.replace("PROPOSAL_INBOX_PATH", f"../../inbox/{project}/index.md"),
        )
    finally:
        os.close(root_fd)
