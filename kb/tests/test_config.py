from __future__ import annotations

from pathlib import Path

import pytest

from eos_kb.config import (
    RegistryError,
    WorkspaceRegistry,
    WorkspaceRoute,
    load_registry,
    match_workspace,
    resolve_workspace,
)
from eos_kb.freshness import CoverageRule


CHECKED_IN_REGISTRY = Path(__file__).resolve().parents[2] / "configs" / "kb" / "workspaces.yaml"


def test_checked_in_registry_expands_home_without_host_state(tmp_path: Path) -> None:
    home = tmp_path / "home"
    registry = load_registry(CHECKED_IN_REGISTRY, home=home, environ={"HOME": str(home)})

    work_project = registry.workspaces[Path(home / "work" / "backend")]
    research_project = registry.workspaces[Path(home / "personal" / "research-project")]
    eos = registry.workspaces[Path(home / "personal" / "eos")]
    assert work_project.kb == home / "work" / "knowledge"
    assert work_project.project == "backend"
    assert research_project.kb == home / "personal" / "knowledge"
    assert research_project.project == "research"
    assert eos.kb == home / "personal" / "knowledge"
    assert eos.project == "eos"


def test_longest_prefix_and_path_boundary_matching(tmp_path: Path) -> None:
    registry_file = tmp_path / "registry.yaml"
    registry_file.write_text(
        "workspaces:\n"
        f"  {tmp_path / 'workspace'}: {{kb: /kb/base, project: base}}\n"
        f"  {tmp_path / 'workspace' / 'project'}: {{kb: /kb/project, project: project}}\n",
        encoding="utf-8",
    )
    registry = load_registry(registry_file, home=tmp_path)

    assert match_workspace(tmp_path / "workspace" / "project" / "src", registry).project == "project"
    assert match_workspace(tmp_path / "workspace" / "project-two", registry).project == "base"


def test_unknown_workspace_is_structured_and_does_not_fall_back_to_work(tmp_path: Path) -> None:
    registry = load_registry(home=tmp_path, environ={"HOME": str(tmp_path)})

    with pytest.raises(RegistryError) as raised:
        resolve_workspace(tmp_path / "personal" / "unknown", registry=registry)

    error = raised.value
    assert error.code == "registry.workspace_not_found"
    assert error.field_path == "$.workspaces"
    assert "register" in error.remediation.lower()


def test_environment_roots_override_checked_in_routes(tmp_path: Path) -> None:
    home = tmp_path / "home"
    work_root = tmp_path / "isolated-work-kb"
    personal_root = tmp_path / "isolated-personal-kb"
    registry = load_registry(
        CHECKED_IN_REGISTRY,
        home=home,
        environ={
            "HOME": str(home),
            "EOS_WORK_KNOWLEDGE_ROOT": str(work_root),
            "EOS_PERSONAL_KNOWLEDGE_ROOT": str(personal_root),
        },
    )

    assert registry.workspaces[home / "work" / "backend"].kb == work_root
    assert registry.workspaces[home / "personal" / "research-project"].kb == personal_root
    assert registry.workspaces[home / "personal" / "eos"].kb == personal_root


def test_invalid_registry_reports_structured_error(tmp_path: Path) -> None:
    path = tmp_path / "invalid.yaml"
    path.write_text("workspaces: []\n", encoding="utf-8")

    with pytest.raises(RegistryError) as raised:
        load_registry(path, home=tmp_path)

    assert raised.value.code == "registry.type"
    assert raised.value.relative_file == "invalid.yaml"
    assert raised.value.field_path == "$.workspaces"


def test_registry_rejects_unknown_route_keys_with_structured_error(tmp_path: Path) -> None:
    path = tmp_path / "unknown-key.yaml"
    path.write_text(
        "workspaces:\n"
        "  /workspace:\n"
        "    kb: /knowledge\n"
        "    project: demo\n"
        "    owner: someone\n",
        encoding="utf-8",
    )

    with pytest.raises(RegistryError) as raised:
        load_registry(path, home=tmp_path)

    assert raised.value.code == "registry.additional_property"
    assert raised.value.relative_file == "unknown-key.yaml"
    assert raised.value.field_path == "$.workspaces./workspace.owner"
    assert raised.value.remediation == "Remove unsupported route key 'owner'."


def test_explicit_kb_from_unregistered_cwd_expands_and_does_not_infer_a_route(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    kb_root = home / "knowledge"
    kb_root.mkdir(parents=True)
    route = WorkspaceRoute(tmp_path / "workspace", kb_root.resolve(), "registered")
    registry = WorkspaceRegistry({route.workspace: route})

    resolved = resolve_workspace(
        tmp_path,
        registry=registry,
        kb=Path("$HOME/other/../knowledge"),
        environ={"HOME": str(home)},
    )

    assert resolved.kb == kb_root.resolve()
    assert resolved.workspace == tmp_path.resolve()
    assert resolved.project == "knowledge"
    assert resolved.registered is False
    assert resolved.coverage == ()


def test_explicit_symlink_equivalent_kb_from_unregistered_cwd_does_not_infer_route(
    tmp_path: Path,
) -> None:
    kb_root = tmp_path / "knowledge"
    kb_root.mkdir()
    alias = tmp_path / "knowledge-alias"
    alias.symlink_to(kb_root, target_is_directory=True)
    route = WorkspaceRoute(tmp_path / "workspace", kb_root.resolve(), "registered")
    registry = WorkspaceRegistry({route.workspace: route})

    resolved = resolve_workspace(tmp_path, registry=registry, kb=alias)

    assert resolved.kb == kb_root.resolve()
    assert resolved.workspace == tmp_path.resolve()
    assert resolved.project == "knowledge"
    assert resolved.registered is False
    assert resolved.coverage == ()


def test_explicit_shared_kb_resolves_project_from_registered_cwd(tmp_path: Path) -> None:
    shared_kb = tmp_path / "knowledge"
    eos_workspace = tmp_path / "eos"
    genesis_workspace = tmp_path / "genesis"
    eos_coverage = (CoverageRule(("scripts/**/*.sh",), ("kb:eos/scripts",)),)
    genesis_coverage = (CoverageRule(("notebooks/**/*.ipynb",), ("kb:genesis/notebooks",)),)
    eos_route = WorkspaceRoute(eos_workspace, shared_kb, "eos", coverage=eos_coverage)
    genesis_route = WorkspaceRoute(
        genesis_workspace,
        shared_kb,
        "nlp-to-llm-evolution",
        coverage=genesis_coverage,
    )
    registry = WorkspaceRegistry({
        eos_workspace: eos_route,
        genesis_workspace: genesis_route,
    })

    eos = resolve_workspace(eos_workspace / "scripts", registry=registry, kb=shared_kb)
    genesis = resolve_workspace(
        genesis_workspace / "notebooks",
        registry=registry,
        kb=shared_kb,
    )

    assert eos.project == "eos"
    assert eos.coverage == eos_coverage
    assert genesis.project == "nlp-to-llm-evolution"
    assert genesis.coverage == genesis_coverage


def test_explicit_kb_uses_nested_registered_route_and_rejects_mismatch(
    tmp_path: Path,
) -> None:
    shared_kb = tmp_path / "knowledge"
    parent_workspace = tmp_path / "workspace"
    nested_workspace = parent_workspace / "nested"
    nested_coverage = (CoverageRule(("src/**/*.py",), ("kb:nested/src",)),)
    parent_route = WorkspaceRoute(parent_workspace, shared_kb, "parent")
    nested_route = WorkspaceRoute(
        nested_workspace,
        shared_kb,
        "nested",
        coverage=nested_coverage,
    )
    registry = WorkspaceRegistry({
        parent_workspace: parent_route,
        nested_workspace: nested_route,
    })

    resolved = resolve_workspace(nested_workspace / "src", registry=registry, kb=shared_kb)

    assert resolved.workspace == nested_workspace
    assert resolved.project == "nested"
    assert resolved.coverage == nested_coverage

    with pytest.raises(RegistryError) as raised:
        resolve_workspace(nested_workspace / "src", registry=registry, kb=tmp_path / "other-kb")

    assert raised.value.code == "registry.kb_mismatch"
    assert raised.value.field_path == "$.kb"


def test_registered_cwd_rejects_conflicting_explicit_kb_and_allows_project_override(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    kb_root = tmp_path / "knowledge"
    route = WorkspaceRoute(workspace, kb_root, "registered")
    registry = WorkspaceRegistry({workspace: route})

    with pytest.raises(RegistryError) as raised:
        resolve_workspace(workspace, registry=registry, kb=tmp_path / "other-kb")

    assert raised.value.code == "registry.kb_mismatch"
    assert raised.value.field_path == "$.kb"

    resolved = resolve_workspace(
        workspace,
        registry=registry,
        kb=kb_root,
        project="override",
    )

    assert resolved.project == "override"
    assert resolved.registered is True


def test_registry_parses_optional_coverage_rules(tmp_path: Path) -> None:
    path = tmp_path / "registry.yaml"
    path.write_text(
        "workspaces:\n"
        "  /workspace:\n"
        "    kb: /knowledge\n"
        "    project: demo\n"
        "    coverage:\n"
        "      - paths: ['src/**/*.py']\n"
        "        concepts: ['kb:demo/runtime']\n"
        "        ignore: ['src/generated/**']\n",
        encoding="utf-8",
    )

    route = load_registry(path, home=tmp_path).workspaces[Path("/workspace")]

    assert route.coverage == (
        CoverageRule(
            paths=("src/**/*.py",),
            concepts=("kb:demo/runtime",),
            ignore=("src/generated/**",),
        ),
    )


@pytest.mark.parametrize(
    "coverage",
    (
        "coverage: {}",
        "coverage: [{paths: src/*.py, concepts: [kb:demo/runtime]}]",
        "coverage: [{paths: [src/*.py], concepts: []}]",
        "coverage: [{paths: [src/*.py], concepts: [kb:demo/runtime], ignore: bad}]",
        "coverage: [{paths: [src/*.py], concepts: [kb:demo/runtime], extra: true}]",
    ),
)
def test_registry_rejects_malformed_coverage_rules(
    tmp_path: Path,
    coverage: str,
) -> None:
    path = tmp_path / "registry.yaml"
    path.write_text(
        "workspaces:\n"
        "  /workspace:\n"
        "    kb: /knowledge\n"
        "    project: demo\n"
        f"    {coverage}\n",
        encoding="utf-8",
    )

    with pytest.raises(RegistryError) as raised:
        load_registry(path, home=tmp_path)

    assert raised.value.code.startswith("registry.coverage")
