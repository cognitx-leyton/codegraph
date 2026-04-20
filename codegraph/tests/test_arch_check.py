"""Tests for :mod:`codegraph.arch_check`.

Each policy function takes a ``neo4j.Driver`` + a per-policy config and runs
two queries: a count query and a sample query. We mock both with a fake
session that dispatches on a substring of the Cypher string. That gives us
policy-level coverage without needing a running Neo4j — the Cypher itself is
smoke-tested by ``codegraph arch-check`` against the live graph in dev.
"""
from __future__ import annotations

import json
from typing import Any

import pytest

from codegraph import arch_check
from codegraph.arch_check import (
    ArchReport,
    PolicyResult,
    _check_coupling_ceiling,
    _check_cross_package,
    _check_custom,
    _check_import_cycles,
    _check_layer_bypass,
    _check_orphans,
    _render,
    run_arch_check,
)
from codegraph.arch_config import (
    ArchConfig,
    CouplingCeilingConfig,
    CrossPackageConfig,
    CrossPackagePair,
    CustomPolicy,
    ImportCyclesConfig,
    LayerBypassConfig,
    OrphanDetectionConfig,
)


# ── Fake Neo4j driver ───────────────────────────────────────────────


class _FakeResult:
    """Stand-in for a Neo4j result object; supports iteration + ``.single()``."""

    def __init__(self, rows: list[dict]):
        self._rows = list(rows)

    def __iter__(self):
        return iter(self._rows)

    def single(self):
        return self._rows[0] if self._rows else None


class _FakeSession:
    """Routes ``run(cypher, **params)`` to a caller-supplied resolver."""

    def __init__(self, resolver):
        self._resolver = resolver

    def run(self, cypher: str, **params: Any) -> _FakeResult:
        return _FakeResult(self._resolver(cypher, **params))

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeDriver:
    def __init__(self, resolver):
        self._resolver = resolver
        self.closed = False

    def session(self):
        return _FakeSession(self._resolver)

    def close(self):
        self.closed = True


def _constant_driver(answers: dict[str, list[dict]]) -> _FakeDriver:
    """Build a driver whose ``session.run`` returns the row list whose key appears in the query."""

    def resolver(cypher: str, **_params):
        for key, rows in answers.items():
            if key in cypher:
                return rows
        return []

    return _FakeDriver(resolver)


# ── Dataclass shape ─────────────────────────────────────────────────


def test_policy_result_defaults():
    p = PolicyResult(name="x", passed=True, violation_count=0)
    assert p.sample == []
    assert p.detail == ""


def test_arch_report_ok_is_true_when_all_pass():
    report = ArchReport(policies=[
        PolicyResult(name="a", passed=True, violation_count=0),
        PolicyResult(name="b", passed=True, violation_count=0),
    ])
    assert report.ok is True


def test_arch_report_ok_is_false_when_any_fails():
    report = ArchReport(policies=[
        PolicyResult(name="a", passed=True, violation_count=0),
        PolicyResult(name="b", passed=False, violation_count=3),
    ])
    assert report.ok is False


def test_arch_report_to_json_is_valid_and_contains_ok_flag():
    report = ArchReport(policies=[
        PolicyResult(name="a", passed=False, violation_count=2, sample=[{"x": 1}]),
    ])
    blob = json.loads(report.to_json())
    assert blob["ok"] is False
    assert blob["policies"][0]["violation_count"] == 2
    assert blob["policies"][0]["sample"] == [{"x": 1}]


# ── import_cycles ───────────────────────────────────────────────────


def test_import_cycles_clean():
    driver = _constant_driver({
        "count(DISTINCT path) AS v": [{"v": 0}],
        "DISTINCT cycle, hops": [],
    })
    result = _check_import_cycles(driver, ImportCyclesConfig())
    assert result.name == "import_cycles"
    assert result.passed is True
    assert result.violation_count == 0
    assert result.sample == []


def test_import_cycles_detected():
    sample = [
        {"cycle": ["a.py", "b.py", "a.py"], "hops": 2},
    ]
    driver = _constant_driver({
        "count(DISTINCT path) AS v": [{"v": 1}],
        "DISTINCT cycle, hops": sample,
    })
    result = _check_import_cycles(driver, ImportCyclesConfig())
    assert result.passed is False
    assert result.violation_count == 1
    assert result.sample == sample


def test_import_cycles_honours_hop_config():
    """Custom hop range should appear in the Cypher sent to the driver."""
    captured: list[str] = []

    def resolver(cypher: str, **_params):
        captured.append(cypher)
        return [{"v": 0}] if "count(DISTINCT path)" in cypher else []

    driver = _FakeDriver(resolver)
    _check_import_cycles(driver, ImportCyclesConfig(min_hops=3, max_hops=4))
    assert any("IMPORTS*3..4" in c for c in captured)


# ── cross_package ───────────────────────────────────────────────────


def test_cross_package_clean():
    driver = _constant_driver({
        "count(*) AS v": [{"v": 0}],
    })
    result = _check_cross_package(driver, CrossPackageConfig())
    assert result.name == "cross_package"
    assert result.passed is True
    assert result.violation_count == 0


def test_cross_package_detected():
    def resolver(cypher: str, **params):
        if "count(*) AS v" in cypher:
            return [{"v": 2}]
        if "RETURN a.path AS importer" in cypher:
            return [
                {"importer": "apps/web/src/a.ts", "importee": "apps/api/src/b.ts"},
                {"importer": "apps/web/src/c.ts", "importee": "apps/api/src/d.ts"},
            ]
        return []

    driver = _FakeDriver(resolver)
    cfg = CrossPackageConfig(pairs=[CrossPackagePair("apps/web", "apps/api")])
    result = _check_cross_package(driver, cfg)
    assert result.passed is False
    assert result.violation_count == 2
    assert result.sample[0]["importer_package"] == "apps/web"
    assert result.sample[0]["importee_package"] == "apps/api"


def test_cross_package_no_pairs_is_trivially_clean():
    driver = _constant_driver({})
    cfg = CrossPackageConfig(pairs=[])
    result = _check_cross_package(driver, cfg)
    assert result.passed is True
    assert result.violation_count == 0


# ── layer_bypass ────────────────────────────────────────────────────


def test_layer_bypass_clean():
    driver = _constant_driver({
        "count(DISTINCT ctrl) AS v": [{"v": 0}],
        "DISTINCT ctrl.name AS controller": [],
    })
    result = _check_layer_bypass(driver, LayerBypassConfig())
    assert result.name == "layer_bypass"
    assert result.passed is True


def test_layer_bypass_detected():
    sample = [
        {"controller": "UserController", "repository": "UserRepository", "method": "find"},
    ]
    driver = _constant_driver({
        "count(DISTINCT ctrl) AS v": [{"v": 1}],
        "DISTINCT ctrl.name AS controller": sample,
    })
    result = _check_layer_bypass(driver, LayerBypassConfig())
    assert result.passed is False
    assert result.violation_count == 1
    assert result.sample == sample


def test_layer_bypass_uses_config_suffixes():
    captured_params: dict = {}

    def resolver(cypher: str, **params):
        captured_params.update(params)
        return [{"v": 0}] if "count(DISTINCT ctrl)" in cypher else []

    driver = _FakeDriver(resolver)
    cfg = LayerBypassConfig(
        controller_labels=["Gateway"],
        repository_suffix="Repo",
        service_suffix="Manager",
        call_depth=5,
    )
    _check_layer_bypass(driver, cfg)
    assert captured_params["repo_suffix"] == "Repo"
    assert captured_params["svc_suffix"] == "Manager"


# ── coupling_ceiling ───────────────────────────────────────────────


def test_coupling_ceiling_clean():
    driver = _constant_driver({
        "count(f) AS v": [{"v": 0}],
    })
    result = _check_coupling_ceiling(driver, CouplingCeilingConfig())
    assert result.name == "coupling_ceiling"
    assert result.passed is True
    assert result.violation_count == 0
    assert result.sample == []


def test_coupling_ceiling_detected():
    sample = [{"file": "src/god_object.ts", "deps": 35}]
    driver = _constant_driver({
        "count(f) AS v": [{"v": 1}],
        "f.path AS file, deps": sample,
    })
    result = _check_coupling_ceiling(driver, CouplingCeilingConfig())
    assert result.passed is False
    assert result.violation_count == 1
    assert result.sample == sample
    assert "file" in result.sample[0]
    assert "deps" in result.sample[0]


def test_coupling_ceiling_uses_config_threshold():
    captured_params: dict = {}

    def resolver(cypher: str, **params):
        captured_params.update(params)
        return [{"v": 0}] if "count(f)" in cypher else []

    driver = _FakeDriver(resolver)
    _check_coupling_ceiling(driver, CouplingCeilingConfig(max_imports=42))
    assert captured_params["threshold"] == 42


# ── orphan_detection ───────────────────────────────────────────────


def test_orphan_detection_clean():
    driver = _constant_driver({
        "count(*) AS v": [{"v": 0}],
    })
    result = _check_orphans(driver, OrphanDetectionConfig())
    assert result.name == "orphan_detection"
    assert result.passed is True
    assert result.violation_count == 0
    assert result.sample == []


def test_orphan_detection_detected():
    sample = [
        {"kind": "orphan_function", "name": "dead_fn", "file": "src/utils.py"},
        {"kind": "orphan_class", "name": "UnusedClass", "file": "src/models.py"},
    ]
    driver = _constant_driver({
        "count(*) AS v": [{"v": 2}],
        "ORDER BY kind, file, name": sample,
    })
    result = _check_orphans(driver, OrphanDetectionConfig())
    assert result.passed is False
    assert result.violation_count == 2
    assert len(result.sample) == 2
    assert result.sample[0]["kind"] == "orphan_function"
    assert result.sample[1]["kind"] == "orphan_class"


def test_orphan_detection_uses_path_prefix():
    captured_params: list[dict] = []

    def resolver(cypher: str, **params):
        captured_params.append(params)
        return [{"v": 0}] if "count(*) AS v" in cypher else []

    driver = _FakeDriver(resolver)
    _check_orphans(driver, OrphanDetectionConfig(path_prefix="src/core/"))
    assert any(p.get("prefix") == "src/core/" for p in captured_params)


def test_orphan_detection_respects_kinds_config():
    captured: list[str] = []

    def resolver(cypher: str, **_params):
        captured.append(cypher)
        return [{"v": 0}] if "count(*) AS v" in cypher else []

    driver = _FakeDriver(resolver)
    _check_orphans(driver, OrphanDetectionConfig(kinds=["function"]))
    # Only function sub-query should appear; class/atom/endpoint should not.
    all_cypher = "\n".join(captured)
    assert "orphan_function" in all_cypher
    assert "orphan_class" not in all_cypher
    assert "orphan_atom" not in all_cypher
    assert "orphan_endpoint" not in all_cypher


def test_orphan_detection_excludes_pytest_entry_points():
    """test_* functions and xunit setup/teardown helpers must not be flagged."""
    captured: list[str] = []

    def resolver(cypher: str, **_params):
        captured.append(cypher)
        return [{"v": 0}] if "count(*) AS v" in cypher else []

    driver = _FakeDriver(resolver)
    _check_orphans(driver, OrphanDetectionConfig(kinds=["function"]))
    all_cypher = "\n".join(captured)
    assert "test_" in all_cypher
    assert "setup_module" in all_cypher


# ── custom policies ─────────────────────────────────────────────────


def test_custom_policy_clean_skips_sample_query():
    """count=0 → sample query is NOT run (saves a round-trip)."""
    queries_run: list[str] = []

    def resolver(cypher: str, **_params):
        queries_run.append(cypher)
        return [{"v": 0}] if "count(n)" in cypher else []

    driver = _FakeDriver(resolver)
    custom = CustomPolicy(
        name="demo",
        description="demo policy",
        count_cypher="MATCH (n) RETURN count(n) AS v",
        sample_cypher="MATCH (n) RETURN n LIMIT 10",
    )
    result = _check_custom(driver, custom)
    assert result.name == "demo"
    assert result.passed is True
    assert result.violation_count == 0
    assert len(queries_run) == 1  # only the count query, not the sample


def test_custom_policy_detects_violations():
    def resolver(cypher: str, **_params):
        if "count(f)" in cypher:
            return [{"v": 3}]
        return [{"path": "a.py"}, {"path": "b.py"}, {"path": "c.py"}]

    driver = _FakeDriver(resolver)
    custom = CustomPolicy(
        name="no_fat_files",
        description="Files over 500 LOC",
        count_cypher="MATCH (f:File) WHERE f.loc > 500 RETURN count(f) AS v",
        sample_cypher="MATCH (f:File) WHERE f.loc > 500 RETURN f.path AS path",
    )
    result = _check_custom(driver, custom)
    assert result.passed is False
    assert result.violation_count == 3
    assert len(result.sample) == 3
    assert result.detail == "Files over 500 LOC"


def test_check_custom_passes_limit_param():
    """_check_custom injects limit= into s.run() for sample_cypher."""
    captured_params: list[dict] = []

    def resolver(cypher: str, **params):
        captured_params.append(params)
        if "count(f)" in cypher:
            return [{"v": 2}]
        return [{"path": "a.py"}, {"path": "b.py"}]

    driver = _FakeDriver(resolver)
    custom = CustomPolicy(
        name="fat_files",
        description="Files over 500 LOC",
        count_cypher="MATCH (f:File) WHERE f.loc > 500 RETURN count(f) AS v",
        sample_cypher="MATCH (f:File) WHERE f.loc > 500 RETURN f.path AS path LIMIT $limit",
    )
    result = _check_custom(driver, custom, sample_limit=25)
    assert result.violation_count == 2
    # The sample_cypher call should have received limit=25
    sample_call_params = captured_params[-1]
    assert sample_call_params["limit"] == 25


def test_check_custom_passes_scope_param():
    """_check_custom injects scope= into s.run() for both queries."""
    captured_params: list[dict] = []

    def resolver(cypher: str, **params):
        captured_params.append(params)
        if "count(f)" in cypher:
            return [{"v": 1}]
        return [{"path": "src/a.py"}]

    driver = _FakeDriver(resolver)
    custom = CustomPolicy(
        name="fat_files",
        description="Files over 500 LOC",
        count_cypher="MATCH (f:File) WHERE f.loc > 500 RETURN count(f) AS v",
        sample_cypher="MATCH (f:File) WHERE f.loc > 500 RETURN f.path AS path LIMIT $limit",
    )
    result = _check_custom(driver, custom, scope=["src/"], sample_limit=10)
    assert result.violation_count == 1
    # Both count and sample calls should have received scope=["src/"]
    assert captured_params[0]["scope"] == ["src/"]
    assert captured_params[1]["scope"] == ["src/"]


# ── Orchestrator ────────────────────────────────────────────────────


def test_run_arch_check_aggregates_five_policies(monkeypatch):
    """``run_arch_check`` opens a driver, runs all 5 built-in policies, closes it."""
    fake_driver = _constant_driver({
        "count(DISTINCT path) AS v": [{"v": 0}],
        "count(*) AS v": [{"v": 0}],
        "count(DISTINCT ctrl) AS v": [{"v": 0}],
        "count(f) AS v": [{"v": 0}],
    })

    def _fake_driver_factory(uri, auth):
        return fake_driver

    monkeypatch.setattr(arch_check.GraphDatabase, "driver", _fake_driver_factory)

    report = run_arch_check(
        "bolt://fake:7687", "neo4j", "pw", console=None, config=ArchConfig(),
    )
    assert fake_driver.closed is True
    assert report.ok is True
    assert [p.name for p in report.policies] == [
        "import_cycles", "cross_package", "layer_bypass", "coupling_ceiling",
        "orphan_detection",
    ]


def test_run_arch_check_with_disabled_policy_emits_skip_marker(monkeypatch):
    # Other policies still run, so the mock must answer their count queries.
    fake_driver = _constant_driver({
        "count(*) AS v": [{"v": 0}],
        "count(DISTINCT ctrl) AS v": [{"v": 0}],
        "count(f) AS v": [{"v": 0}],
    })
    monkeypatch.setattr(arch_check.GraphDatabase, "driver", lambda uri, auth: fake_driver)

    config = ArchConfig(import_cycles=ImportCyclesConfig(enabled=False))
    report = run_arch_check("bolt://fake:7687", "neo4j", "pw", console=None, config=config)

    cycles = next(p for p in report.policies if p.name == "import_cycles")
    assert cycles.passed is True
    assert "disabled" in cycles.detail


def test_run_arch_check_runs_custom_policies(monkeypatch):
    """Custom policies in the config are evaluated after built-ins."""
    def resolver(cypher: str, **_params):
        if "count(DISTINCT path)" in cypher:
            return [{"v": 0}]
        if "count(*)" in cypher:
            return [{"v": 0}]
        if "count(DISTINCT ctrl)" in cypher:
            return [{"v": 0}]
        if "count(f) AS v" in cypher:
            return [{"v": 0}]
        if "count(custom_node)" in cypher:
            return [{"v": 1}]
        return [{"x": "violation"}]

    fake_driver = _FakeDriver(resolver)
    monkeypatch.setattr(arch_check.GraphDatabase, "driver", lambda uri, auth: fake_driver)

    custom = CustomPolicy(
        name="my_rule",
        description="demo",
        count_cypher="MATCH (custom_node) RETURN count(custom_node) AS v",
        sample_cypher="MATCH (n) RETURN n AS x LIMIT $limit",
    )
    config = ArchConfig(custom=[custom])
    report = run_arch_check("bolt://fake:7687", "neo4j", "pw", console=None, config=config)

    policy_names = [p.name for p in report.policies]
    assert policy_names == [
        "import_cycles", "cross_package", "layer_bypass", "coupling_ceiling",
        "orphan_detection", "my_rule",
    ]
    my_rule = report.policies[-1]
    assert my_rule.passed is False
    assert my_rule.violation_count == 1


def test_run_arch_check_closes_driver_even_on_failure(monkeypatch):
    fake_driver = _constant_driver({})
    fake_driver._resolver = lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("boom"))
    monkeypatch.setattr(arch_check.GraphDatabase, "driver", lambda uri, auth: fake_driver)

    with pytest.raises(RuntimeError):
        run_arch_check(
            "bolt://fake:7687", "neo4j", "pw", console=None, config=ArchConfig(),
        )
    assert fake_driver.closed is True


# ── --scope filtering ──────────────────────────────────────────────────


def test_import_cycles_with_scope():
    """Scope adds a WHERE … STARTS WITH clause and passes params."""
    captured: list[str] = []
    captured_params: list[dict] = []

    def resolver(cypher: str, **params):
        captured.append(cypher)
        captured_params.append(params)
        return [{"v": 0}] if "count(DISTINCT path)" in cypher else []

    driver = _FakeDriver(resolver)
    _check_import_cycles(driver, ImportCyclesConfig(), scope=["src/"])
    all_cypher = "\n".join(captured)
    assert "STARTS WITH $_scope0" in all_cypher
    assert any(p.get("_scope0") == "src/" for p in captured_params)


def test_import_cycles_with_multiple_scopes():
    """Multiple scope prefixes produce OR-joined conditions and distinct params."""
    captured: list[str] = []
    captured_params: list[dict] = []

    def resolver(cypher: str, **params):
        captured.append(cypher)
        captured_params.append(params)
        return [{"v": 0}] if "count(DISTINCT path)" in cypher else []

    driver = _FakeDriver(resolver)
    _check_import_cycles(driver, ImportCyclesConfig(), scope=["src/", "lib/"])
    all_cypher = "\n".join(captured)
    assert "STARTS WITH $_scope0" in all_cypher
    assert "STARTS WITH $_scope1" in all_cypher
    assert " OR " in all_cypher
    assert any(
        p.get("_scope0") == "src/" and p.get("_scope1") == "lib/"
        for p in captured_params
    )


def test_import_cycles_no_scope_no_where():
    """Without scope, no STARTS WITH clause appears — backwards compat."""
    captured: list[str] = []

    def resolver(cypher: str, **_params):
        captured.append(cypher)
        return [{"v": 0}] if "count(DISTINCT path)" in cypher else []

    driver = _FakeDriver(resolver)
    _check_import_cycles(driver, ImportCyclesConfig(), scope=None)
    all_cypher = "\n".join(captured)
    assert "STARTS WITH" not in all_cypher


def test_cross_package_with_scope():
    captured_params: list[dict] = []

    def resolver(cypher: str, **params):
        captured_params.append(params)
        if "count(*) AS v" in cypher:
            return [{"v": 0}]
        return []

    driver = _FakeDriver(resolver)
    _check_cross_package(driver, CrossPackageConfig(), scope=["apps/"])
    assert any(p.get("_scope0") == "apps/" for p in captured_params)


def test_layer_bypass_with_scope():
    captured: list[str] = []
    captured_params: list[dict] = []

    def resolver(cypher: str, **params):
        captured.append(cypher)
        captured_params.append(params)
        return [{"v": 0}] if "count(DISTINCT ctrl)" in cypher else []

    driver = _FakeDriver(resolver)
    _check_layer_bypass(driver, LayerBypassConfig(), scope=["src/"])
    all_cypher = "\n".join(captured)
    assert "ctrl.file STARTS WITH $_scope0" in all_cypher
    assert any(p.get("_scope0") == "src/" for p in captured_params)


def test_coupling_ceiling_with_scope():
    captured: list[str] = []
    captured_params: list[dict] = []

    def resolver(cypher: str, **params):
        captured.append(cypher)
        captured_params.append(params)
        return [{"v": 0}] if "count(f) AS v" in cypher else []

    driver = _FakeDriver(resolver)
    _check_coupling_ceiling(driver, CouplingCeilingConfig(), scope=["codegraph/"])
    all_cypher = "\n".join(captured)
    # Scope WHERE must appear BEFORE the WITH aggregation
    for cypher in captured:
        if "STARTS WITH" in cypher:
            starts_with_pos = cypher.index("STARTS WITH")
            with_pos = cypher.index("WITH f, count")
            assert starts_with_pos < with_pos, \
                "scope filter must appear before WITH aggregation"
    assert any(p.get("_scope0") == "codegraph/" for p in captured_params)


def test_orphan_detection_scope_overrides_empty_path_prefix():
    """When path_prefix is empty, scope is used for orphan filtering."""
    captured_params: list[dict] = []

    def resolver(cypher: str, **params):
        captured_params.append(params)
        return [{"v": 0}] if "count(*) AS v" in cypher else []

    driver = _FakeDriver(resolver)
    _check_orphans(
        driver,
        OrphanDetectionConfig(path_prefix=""),
        scope=["src/"],
    )
    assert any(p.get("_scope0") == "src/" for p in captured_params)
    # No $prefix param should be set
    assert not any("prefix" in p for p in captured_params)


def test_orphan_detection_path_prefix_takes_precedence_over_scope():
    """Explicit path_prefix wins over --scope."""
    captured_params: list[dict] = []

    def resolver(cypher: str, **params):
        captured_params.append(params)
        return [{"v": 0}] if "count(*) AS v" in cypher else []

    driver = _FakeDriver(resolver)
    _check_orphans(
        driver,
        OrphanDetectionConfig(path_prefix="core/"),
        scope=["src/"],
    )
    assert any(p.get("prefix") == "core/" for p in captured_params)
    # _scope0 must NOT be set — path_prefix takes precedence
    assert not any("_scope0" in p for p in captured_params)


def test_run_arch_check_passes_scope_to_policies(monkeypatch):
    """run_arch_check forwards scope to _run_all and all built-in policies."""
    fake_driver = _constant_driver({
        "count(DISTINCT path) AS v": [{"v": 0}],
        "count(*) AS v": [{"v": 0}],
        "count(DISTINCT ctrl) AS v": [{"v": 0}],
        "count(f) AS v": [{"v": 0}],
    })
    monkeypatch.setattr(arch_check.GraphDatabase, "driver", lambda uri, auth: fake_driver)

    # Capture what _run_all receives
    original_run_all = arch_check._run_all
    received_scope = []

    def spy_run_all(driver, config, scope=None, sample_limit=10):
        received_scope.append(scope)
        return original_run_all(driver, config, scope, sample_limit)

    monkeypatch.setattr(arch_check, "_run_all", spy_run_all)

    run_arch_check(
        "bolt://fake:7687", "neo4j", "pw",
        console=None, config=ArchConfig(),
        scope=["x/", "y/"],
    )
    assert received_scope == [["x/", "y/"]]


# ── Suppression ───────────────────────────────────────────────────


from codegraph.arch_check import (
    _apply_suppressions,
    _match_suppression_key,
    _violation_key,
)
from codegraph.arch_config import Suppression


# ── _violation_key ─────────────────────────────────────────────


def test_violation_key_import_cycles():
    row = {"cycle": ["a.py", "b.py", "a.py"], "hops": 2}
    assert _violation_key("import_cycles", row) == "a.py -> b.py -> a.py"


def test_violation_key_cross_package():
    row = {
        "importer_package": "web",
        "importee_package": "api",
        "importer": "web/a.ts",
        "importee": "api/b.ts",
    }
    assert _violation_key("cross_package", row) == "web/a.ts -> api/b.ts"


def test_violation_key_coupling_ceiling():
    row = {"file": "src/app.ts", "deps": 30}
    assert _violation_key("coupling_ceiling", row) == "src/app.ts"


def test_violation_key_orphan_detection():
    row = {"kind": "orphan_function", "name": "dead_fn", "file": "src/utils.py"}
    assert _violation_key("orphan_detection", row) == "orphan_function:dead_fn"


def test_violation_key_layer_bypass():
    row = {"controller": "UserCtrl", "repository": "UserRepo", "method": "find"}
    assert _violation_key("layer_bypass", row) == "UserCtrl -> UserRepo.find"


def test_violation_key_custom_fallback():
    row = {"path": "big.py", "loc": 999}
    assert _violation_key("my_custom_rule", row) == "big.py | 999"


# ── _match_suppression_key ─────────────────────────────────────


def test_match_suppression_exact():
    row = {"file": "src/app.ts", "deps": 30}
    assert _match_suppression_key("coupling_ceiling", row, "src/app.ts") is True


def test_match_suppression_cycle_edge():
    """Edge key 'A -> B' matches any cycle containing that consecutive pair."""
    row = {"cycle": ["a.py", "b.py", "c.py", "a.py"], "hops": 3}
    assert _match_suppression_key("import_cycles", row, "a.py -> b.py") is True
    assert _match_suppression_key("import_cycles", row, "b.py -> c.py") is True
    assert _match_suppression_key("import_cycles", row, "c.py -> a.py") is True


def test_match_suppression_no_match():
    row = {"file": "src/app.ts", "deps": 30}
    assert _match_suppression_key("coupling_ceiling", row, "src/other.ts") is False


def test_match_suppression_cycle_edge_no_match():
    row = {"cycle": ["a.py", "b.py", "a.py"], "hops": 2}
    assert _match_suppression_key("import_cycles", row, "x.py -> y.py") is False


# ── _apply_suppressions ─────────────────────────────────────────


def test_apply_suppressions_all_suppressed_passes():
    policies = [
        PolicyResult(
            name="coupling_ceiling",
            passed=False,
            violation_count=2,
            sample=[
                {"file": "a.ts", "deps": 25},
                {"file": "b.ts", "deps": 30},
            ],
        ),
    ]
    supps = [
        Suppression(policy="coupling_ceiling", key="a.ts", reason="r1"),
        Suppression(policy="coupling_ceiling", key="b.ts", reason="r2"),
    ]
    updated, stale = _apply_suppressions(policies, supps)
    p = updated[0]
    assert p.passed is True
    assert p.violation_count == 0
    assert p.suppressed_count == 2
    assert len(p.suppressed_sample) == 2
    assert p.sample == []
    assert stale == []


def test_apply_suppressions_partial():
    policies = [
        PolicyResult(
            name="coupling_ceiling",
            passed=False,
            violation_count=3,
            sample=[
                {"file": "a.ts", "deps": 25},
                {"file": "b.ts", "deps": 30},
                {"file": "c.ts", "deps": 40},
            ],
        ),
    ]
    supps = [
        Suppression(policy="coupling_ceiling", key="a.ts", reason="r1"),
    ]
    updated, stale = _apply_suppressions(policies, supps)
    p = updated[0]
    assert p.passed is False
    assert p.violation_count == 2
    assert p.suppressed_count == 1
    assert len(p.sample) == 2
    assert stale == []


def test_apply_suppressions_stale_detected():
    policies = [
        PolicyResult(
            name="coupling_ceiling",
            passed=True,
            violation_count=0,
            sample=[],
        ),
    ]
    supps = [
        Suppression(policy="coupling_ceiling", key="gone.ts", reason="was needed"),
    ]
    updated, stale = _apply_suppressions(policies, supps)
    assert len(stale) == 1
    assert stale[0]["policy"] == "coupling_ceiling"
    assert stale[0]["key"] == "gone.ts"
    assert stale[0]["reason"] == "was needed"


def test_apply_suppressions_empty_list_is_noop():
    policies = [
        PolicyResult(name="x", passed=True, violation_count=0),
    ]
    updated, stale = _apply_suppressions(policies, [])
    assert updated is policies  # same object, untouched
    assert stale == []


def test_apply_suppressions_incomplete_coverage_when_truncated():
    """Flag set when violation_count > len(sample) and suppressions match."""
    sample = [{"file": f"f{i}.ts", "deps": 20 + i} for i in range(10)]
    policies = [
        PolicyResult(
            name="coupling_ceiling",
            passed=False,
            violation_count=20,  # more than the 10 sample rows
            sample=sample,
        ),
    ]
    supps = [
        Suppression(policy="coupling_ceiling", key="f0.ts", reason="ok"),
    ]
    updated, stale = _apply_suppressions(policies, supps)
    p = updated[0]
    assert p.incomplete_suppression_coverage is True
    assert p.passed is False
    assert p.suppressed_count == 1
    assert p.violation_count == 19
    assert stale == []


def test_apply_suppressions_no_incomplete_flag_when_count_equals_sample():
    """No flag when violation_count == len(sample) and all suppressed."""
    policies = [
        PolicyResult(
            name="coupling_ceiling",
            passed=False,
            violation_count=2,
            sample=[
                {"file": "a.ts", "deps": 25},
                {"file": "b.ts", "deps": 30},
            ],
        ),
    ]
    supps = [
        Suppression(policy="coupling_ceiling", key="a.ts", reason="r1"),
        Suppression(policy="coupling_ceiling", key="b.ts", reason="r2"),
    ]
    updated, stale = _apply_suppressions(policies, supps)
    p = updated[0]
    assert p.incomplete_suppression_coverage is False
    assert p.passed is True
    assert p.violation_count == 0


def test_apply_suppressions_no_incomplete_flag_when_no_suppression_matches():
    """No flag when truncated but zero suppressions match."""
    sample = [{"file": f"f{i}.ts", "deps": 20 + i} for i in range(10)]
    policies = [
        PolicyResult(
            name="coupling_ceiling",
            passed=False,
            violation_count=20,
            sample=sample,
        ),
    ]
    supps = [
        Suppression(policy="coupling_ceiling", key="nonexistent.ts", reason="r"),
    ]
    updated, stale = _apply_suppressions(policies, supps)
    p = updated[0]
    assert p.incomplete_suppression_coverage is False
    assert p.passed is False


def test_invariant_incomplete_implies_not_passed():
    """Invariant: incomplete_suppression_coverage=True implies passed=False.

    When violation_count > len(sample) and all sample rows are suppressed,
    unseen violations beyond the sample window keep passed=False.
    """
    sample = [{"file": f"f{i}.ts", "deps": 20 + i} for i in range(10)]
    policies = [
        PolicyResult(
            name="coupling_ceiling",
            passed=False,
            violation_count=15,  # 5 more than the 10 sample rows
            sample=sample,
        ),
    ]
    supps = [
        Suppression(policy="coupling_ceiling", key=f"f{i}.ts", reason="ok")
        for i in range(10)
    ]
    updated, _stale = _apply_suppressions(policies, supps)
    p = updated[0]
    assert p.incomplete_suppression_coverage is True
    assert p.passed is False, (
        "invariant: incomplete_suppression_coverage=True must imply passed=False"
    )
    assert p.violation_count == 5  # 15 total - 10 suppressed = 5 unseen


def test_incomplete_suppression_coverage_in_json():
    """The flag appears in JSON output via asdict()."""
    report = ArchReport(
        policies=[
            PolicyResult(
                name="import_cycles",
                passed=False,
                violation_count=10,
                incomplete_suppression_coverage=True,
            ),
        ],
    )
    blob = json.loads(report.to_json())
    assert blob["policies"][0]["incomplete_suppression_coverage"] is True

    # Also check False is serialised.
    report2 = ArchReport(
        policies=[
            PolicyResult(name="x", passed=True, violation_count=0),
        ],
    )
    blob2 = json.loads(report2.to_json())
    assert blob2["policies"][0]["incomplete_suppression_coverage"] is False


def test_render_incomplete_coverage_warning():
    """_render emits a warning when incomplete_suppression_coverage is True."""
    from io import StringIO

    from rich.console import Console

    report = ArchReport(
        policies=[
            PolicyResult(
                name="import_cycles",
                passed=False,
                violation_count=15,
                sample=[{"cycle": ["a.py", "b.py", "a.py"], "hops": 2}],
                suppressed_count=5,
                suppressed_sample=[
                    {"cycle": ["c.py", "d.py", "c.py"], "hops": 2},
                ],
                incomplete_suppression_coverage=True,
            ),
        ],
    )
    buf = StringIO()
    _render(Console(file=buf, force_terminal=True, width=200), report)
    output = buf.getvalue()
    assert "suppression coverage is partial" in output
    assert "import_cycles" in output


def test_render_no_warning_when_coverage_complete():
    """_render does NOT emit the warning when the flag is False."""
    from io import StringIO

    from rich.console import Console

    report = ArchReport(
        policies=[
            PolicyResult(
                name="import_cycles",
                passed=True,
                violation_count=0,
                suppressed_count=2,
                incomplete_suppression_coverage=False,
            ),
        ],
    )
    buf = StringIO()
    _render(Console(file=buf, force_terminal=True, width=200), report)
    output = buf.getvalue()
    assert "suppression coverage is partial" not in output


# ── Integration: run_arch_check + suppressions ──────────────────


def test_run_arch_check_with_suppressions_exits_zero(monkeypatch):
    """All violations suppressed → report.ok is True."""
    sample = [{"file": "god.ts", "deps": 50}]
    fake_driver = _constant_driver({
        "count(DISTINCT path) AS v": [{"v": 0}],
        "count(*) AS v": [{"v": 0}],
        "count(DISTINCT ctrl) AS v": [{"v": 0}],
        "count(f) AS v": [{"v": 1}],
        "f.path AS file, deps": sample,
    })
    monkeypatch.setattr(arch_check.GraphDatabase, "driver", lambda uri, auth: fake_driver)

    config = ArchConfig(
        suppressions=[
            Suppression(
                policy="coupling_ceiling",
                key="god.ts",
                reason="Legacy monolith file",
            ),
        ],
    )
    report = run_arch_check(
        "bolt://fake:7687", "neo4j", "pw", console=None, config=config,
    )
    assert report.ok is True
    coupling = next(p for p in report.policies if p.name == "coupling_ceiling")
    assert coupling.passed is True
    assert coupling.suppressed_count == 1
    assert coupling.violation_count == 0


def test_run_arch_check_suppressions_in_json(monkeypatch):
    """JSON output includes suppressed_count and stale_suppressions."""
    sample = [{"file": "god.ts", "deps": 50}]
    fake_driver = _constant_driver({
        "count(DISTINCT path) AS v": [{"v": 0}],
        "count(*) AS v": [{"v": 0}],
        "count(DISTINCT ctrl) AS v": [{"v": 0}],
        "count(f) AS v": [{"v": 1}],
        "f.path AS file, deps": sample,
    })
    monkeypatch.setattr(arch_check.GraphDatabase, "driver", lambda uri, auth: fake_driver)

    config = ArchConfig(
        suppressions=[
            Suppression(
                policy="coupling_ceiling",
                key="god.ts",
                reason="Legacy",
            ),
            Suppression(
                policy="import_cycles",
                key="x.py -> y.py",
                reason="Stale entry",
            ),
        ],
    )
    report = run_arch_check(
        "bolt://fake:7687", "neo4j", "pw", console=None, config=config,
    )
    blob = json.loads(report.to_json())
    assert blob["ok"] is True

    # suppressed_count should be in the per-policy data
    coupling = next(p for p in blob["policies"] if p["name"] == "coupling_ceiling")
    assert coupling["suppressed_count"] == 1

    # The stale entry should appear
    assert len(blob["stale_suppressions"]) == 1
    assert blob["stale_suppressions"][0]["policy"] == "import_cycles"
    assert blob["stale_suppressions"][0]["key"] == "x.py -> y.py"


# ── CLI auto-scope tests ──────────────────────────────────────────────


def _ok_report():
    """Return a passing ArchReport with no violations."""
    return ArchReport(policies=[], stale_suppressions=[])


def _patch_cli(monkeypatch, config_packages=None, config_source=None):
    """Patch run_arch_check, load_arch_config, and load_config for CLI tests.

    Returns a dict whose ``"scope"`` key is set by the patched
    ``run_arch_check`` each time it's called, so the test can inspect
    what scope the CLI passed through.
    """
    from codegraph import cli as cli_mod
    from codegraph.config import CodegraphConfig

    captured: dict[str, Any] = {"scope": "NOT_CALLED"}

    def fake_run(uri, user, password, *, console=None, config=None, scope=None):
        captured["scope"] = scope
        return _ok_report()

    def fake_load_arch_config(repo, *, path=None):
        return ArchConfig()

    cfg = CodegraphConfig(
        packages=config_packages or [],
        source=config_source,
    )

    monkeypatch.setattr("codegraph.arch_check.run_arch_check", fake_run)
    monkeypatch.setattr("codegraph.arch_config.load_arch_config", fake_load_arch_config)
    monkeypatch.setattr(cli_mod, "load_config", lambda repo: cfg)
    return captured


def test_arch_check_cli_auto_scope_from_config(monkeypatch):
    """When no --scope / --no-scope, packages from config become scope."""
    from typer.testing import CliRunner
    from codegraph.cli import app

    captured = _patch_cli(
        monkeypatch,
        config_packages=["packages/server", "packages/web"],
        config_source="codegraph.toml",
    )
    result = CliRunner().invoke(app, ["arch-check"])
    assert result.exit_code == 0
    assert captured["scope"] == ["packages/server", "packages/web"]


def test_arch_check_cli_explicit_scope_overrides_config(monkeypatch):
    """Explicit --scope wins over config packages."""
    from typer.testing import CliRunner
    from codegraph.cli import app

    captured = _patch_cli(
        monkeypatch,
        config_packages=["packages/server"],
        config_source="codegraph.toml",
    )
    result = CliRunner().invoke(app, ["arch-check", "--scope", "other/path"])
    assert result.exit_code == 0
    assert captured["scope"] == ["other/path"]


def test_arch_check_cli_no_scope_flag_disables_auto(monkeypatch):
    """--no-scope disables auto-scope even with packages configured."""
    from typer.testing import CliRunner
    from codegraph.cli import app

    captured = _patch_cli(
        monkeypatch,
        config_packages=["packages/server"],
        config_source="codegraph.toml",
    )
    result = CliRunner().invoke(app, ["arch-check", "--no-scope"])
    assert result.exit_code == 0
    assert captured["scope"] is None


def test_arch_check_cli_no_config_no_scope_passes_none(monkeypatch):
    """No config packages + no flags → scope=None (check entire graph)."""
    from typer.testing import CliRunner
    from codegraph.cli import app

    captured = _patch_cli(monkeypatch)  # no packages
    result = CliRunner().invoke(app, ["arch-check"])
    assert result.exit_code == 0
    assert captured["scope"] is None


# ── sample_limit threading ──────────────────────────────────────────


def test_sample_limit_threaded_to_policy_queries(monkeypatch):
    """run_arch_check with sample_limit=25 passes limit=25 to Neo4j queries."""
    captured_limits: list[int] = []

    def resolver(cypher: str, **params):
        if "limit" in params:
            captured_limits.append(params["limit"])
        if "count(DISTINCT path)" in cypher:
            return [{"v": 0}]
        if "count(*)" in cypher:
            return [{"v": 0}]
        if "count(DISTINCT ctrl)" in cypher:
            return [{"v": 0}]
        if "count(f) AS v" in cypher:
            return [{"v": 0}]
        return []

    fake_driver = _FakeDriver(resolver)
    monkeypatch.setattr(arch_check.GraphDatabase, "driver", lambda uri, auth: fake_driver)

    config = ArchConfig(sample_limit=25)
    run_arch_check(
        "bolt://fake:7687", "neo4j", "pw", console=None, config=config,
    )
    assert captured_limits, "expected at least one limit param captured"
    assert all(lim == 25 for lim in captured_limits), (
        f"expected all limits to be 25, got {captured_limits}"
    )


def test_render_incomplete_warning_references_config():
    """Warning message references settings.sample_limit, not SAMPLE_LIMIT."""
    from io import StringIO

    from rich.console import Console

    report = ArchReport(
        policies=[
            PolicyResult(
                name="import_cycles",
                passed=False,
                violation_count=15,
                sample=[{"cycle": ["a.py", "b.py", "a.py"], "hops": 2}],
                suppressed_count=5,
                suppressed_sample=[
                    {"cycle": ["c.py", "d.py", "c.py"], "hops": 2},
                ],
                incomplete_suppression_coverage=True,
            ),
        ],
    )
    buf = StringIO()
    _render(Console(file=buf, force_terminal=True, width=200), report)
    output = buf.getvalue()
    assert "settings.sample_limit" in output
    assert ".arch-policies.toml" in output
    assert "SAMPLE_LIMIT" not in output
