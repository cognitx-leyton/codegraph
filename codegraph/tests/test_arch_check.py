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
        sample_cypher="MATCH (n) RETURN n AS x LIMIT 10",
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
