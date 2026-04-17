"""Tests for :mod:`codegraph.arch_config`.

Every test writes a tiny TOML file into ``tmp_path`` and calls
:func:`load_arch_config`. Validation errors surface as
:class:`ArchConfigError`.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from codegraph.arch_config import (
    ArchConfig,
    ArchConfigError,
    CrossPackagePair,
    CustomPolicy,
    load_arch_config,
)


# ── Helpers ─────────────────────────────────────────────────


def _write(tmp_path: Path, content: str) -> Path:
    p = tmp_path / ".arch-policies.toml"
    p.write_text(content, encoding="utf-8")
    return p


# ── Defaults / missing file ─────────────────────────────────


def test_missing_file_returns_defaults(tmp_path: Path):
    cfg = load_arch_config(tmp_path)
    assert isinstance(cfg, ArchConfig)
    assert cfg.import_cycles.enabled is True
    assert cfg.import_cycles.min_hops == 2
    assert cfg.import_cycles.max_hops == 6
    assert cfg.cross_package.enabled is True
    assert cfg.cross_package.pairs == [
        CrossPackagePair(importer="twenty-front", importee="twenty-server"),
    ]
    assert cfg.layer_bypass.enabled is True
    assert cfg.layer_bypass.controller_labels == ["Controller"]
    assert cfg.layer_bypass.repository_suffix == "Repository"
    assert cfg.layer_bypass.service_suffix == "Service"
    assert cfg.layer_bypass.call_depth == 3
    assert cfg.coupling_ceiling.enabled is True
    assert cfg.coupling_ceiling.max_imports == 20
    assert cfg.orphan_detection.enabled is True
    assert cfg.orphan_detection.path_prefix == ""
    assert cfg.orphan_detection.kinds == ["function", "class", "atom", "endpoint"]
    assert cfg.custom == []
    assert cfg.schema_version == 1


def test_empty_file_returns_defaults(tmp_path: Path):
    _write(tmp_path, "")
    cfg = load_arch_config(tmp_path)
    assert cfg.import_cycles.enabled is True
    assert cfg.custom == []


def test_explicit_path_override(tmp_path: Path):
    custom_path = tmp_path / "my-policies.toml"
    custom_path.write_text("[policies.import_cycles]\nenabled = false\n")
    cfg = load_arch_config(tmp_path, path=custom_path)
    assert cfg.import_cycles.enabled is False


# ── Schema versioning ─────────────────────────────────────


def test_missing_meta_defaults_to_version_1(tmp_path: Path):
    _write(tmp_path, """
[policies.import_cycles]
enabled = false
""")
    cfg = load_arch_config(tmp_path)
    assert cfg.schema_version == 1


def test_explicit_version_1_accepted(tmp_path: Path):
    _write(tmp_path, """
[meta]
schema_version = 1
""")
    cfg = load_arch_config(tmp_path)
    assert cfg.schema_version == 1


def test_future_version_rejected(tmp_path: Path):
    _write(tmp_path, """
[meta]
schema_version = 99
""")
    with pytest.raises(ArchConfigError, match="not supported.*upgrade"):
        load_arch_config(tmp_path)


def test_version_zero_rejected(tmp_path: Path):
    _write(tmp_path, """
[meta]
schema_version = 0
""")
    with pytest.raises(ArchConfigError, match="positive integer"):
        load_arch_config(tmp_path)


def test_version_wrong_type_rejected(tmp_path: Path):
    _write(tmp_path, """
[meta]
schema_version = "1"
""")
    with pytest.raises(ArchConfigError, match="must be an integer"):
        load_arch_config(tmp_path)


def test_version_bool_rejected(tmp_path: Path):
    _write(tmp_path, """
[meta]
schema_version = true
""")
    with pytest.raises(ArchConfigError, match="must be an integer"):
        load_arch_config(tmp_path)


def test_meta_must_be_table(tmp_path: Path):
    _write(tmp_path, 'meta = "wrong"\n')
    with pytest.raises(ArchConfigError, match=r"\[meta\] must be a table"):
        load_arch_config(tmp_path)


# ── Built-in policy tuning ──────────────────────────────────


def test_disable_import_cycles(tmp_path: Path):
    _write(tmp_path, """
[policies.import_cycles]
enabled = false
""")
    cfg = load_arch_config(tmp_path)
    assert cfg.import_cycles.enabled is False
    # Other built-ins stay default
    assert cfg.cross_package.enabled is True


def test_tune_import_cycles_hops(tmp_path: Path):
    _write(tmp_path, """
[policies.import_cycles]
min_hops = 3
max_hops = 8
""")
    cfg = load_arch_config(tmp_path)
    assert cfg.import_cycles.min_hops == 3
    assert cfg.import_cycles.max_hops == 8


def test_import_cycles_min_below_2_rejected(tmp_path: Path):
    _write(tmp_path, """
[policies.import_cycles]
min_hops = 1
""")
    with pytest.raises(ArchConfigError, match="min_hops must be >= 2"):
        load_arch_config(tmp_path)


def test_import_cycles_max_below_min_rejected(tmp_path: Path):
    _write(tmp_path, """
[policies.import_cycles]
min_hops = 5
max_hops = 3
""")
    with pytest.raises(ArchConfigError, match="must be >= min_hops"):
        load_arch_config(tmp_path)


def test_override_cross_package_pairs(tmp_path: Path):
    _write(tmp_path, """
[policies.cross_package]
pairs = [
  { importer = "apps/web", importee = "apps/api" },
  { importer = "packages/ui", importee = "packages/core" },
]
""")
    cfg = load_arch_config(tmp_path)
    assert cfg.cross_package.pairs == [
        CrossPackagePair(importer="apps/web", importee="apps/api"),
        CrossPackagePair(importer="packages/ui", importee="packages/core"),
    ]


def test_cross_package_missing_key_rejected(tmp_path: Path):
    _write(tmp_path, """
[policies.cross_package]
pairs = [ { importer = "apps/web" } ]
""")
    with pytest.raises(ArchConfigError, match="missing key"):
        load_arch_config(tmp_path)


def test_tune_layer_bypass(tmp_path: Path):
    _write(tmp_path, """
[policies.layer_bypass]
controller_labels = ["Controller", "Gateway"]
repository_suffix = "Repo"
service_suffix    = "Manager"
call_depth        = 4
""")
    cfg = load_arch_config(tmp_path)
    assert cfg.layer_bypass.controller_labels == ["Controller", "Gateway"]
    assert cfg.layer_bypass.repository_suffix == "Repo"
    assert cfg.layer_bypass.service_suffix == "Manager"
    assert cfg.layer_bypass.call_depth == 4


def test_layer_bypass_empty_labels_rejected(tmp_path: Path):
    _write(tmp_path, """
[policies.layer_bypass]
controller_labels = []
""")
    with pytest.raises(ArchConfigError, match="must not be empty"):
        load_arch_config(tmp_path)


# ── Coupling ceiling ──────────────────────────────────────────


def test_tune_coupling_ceiling(tmp_path: Path):
    _write(tmp_path, """
[policies.coupling_ceiling]
max_imports = 10
""")
    cfg = load_arch_config(tmp_path)
    assert cfg.coupling_ceiling.max_imports == 10
    assert cfg.coupling_ceiling.enabled is True


def test_coupling_ceiling_disabled(tmp_path: Path):
    _write(tmp_path, """
[policies.coupling_ceiling]
enabled = false
""")
    cfg = load_arch_config(tmp_path)
    assert cfg.coupling_ceiling.enabled is False


def test_coupling_ceiling_max_imports_below_1_rejected(tmp_path: Path):
    _write(tmp_path, """
[policies.coupling_ceiling]
max_imports = 0
""")
    with pytest.raises(ArchConfigError, match="max_imports must be >= 1"):
        load_arch_config(tmp_path)


# ── Custom policies ─────────────────────────────────────────


def test_single_custom_policy(tmp_path: Path):
    _write(tmp_path, """
[[policies.custom]]
name          = "no_fat_files"
description   = "Files over 500 LOC"
count_cypher  = "MATCH (f:File) WHERE f.loc > 500 RETURN count(f) AS v"
sample_cypher = "MATCH (f:File) WHERE f.loc > 500 RETURN f.path LIMIT 10"
""")
    cfg = load_arch_config(tmp_path)
    assert len(cfg.custom) == 1
    c = cfg.custom[0]
    assert c.name == "no_fat_files"
    assert c.description == "Files over 500 LOC"
    assert c.enabled is True


def test_multiple_custom_policies(tmp_path: Path):
    _write(tmp_path, """
[[policies.custom]]
name          = "a"
count_cypher  = "MATCH (n) RETURN count(n) AS v"
sample_cypher = "MATCH (n) RETURN n LIMIT 1"

[[policies.custom]]
name          = "b"
enabled       = false
count_cypher  = "MATCH (x) RETURN count(x) AS v"
sample_cypher = "MATCH (x) RETURN x LIMIT 1"
""")
    cfg = load_arch_config(tmp_path)
    assert [c.name for c in cfg.custom] == ["a", "b"]
    assert cfg.custom[1].enabled is False


def test_custom_duplicate_names_rejected(tmp_path: Path):
    _write(tmp_path, """
[[policies.custom]]
name          = "dupe"
count_cypher  = "MATCH (n) RETURN count(n) AS v"
sample_cypher = "MATCH (n) RETURN n"

[[policies.custom]]
name          = "dupe"
count_cypher  = "MATCH (m) RETURN count(m) AS v"
sample_cypher = "MATCH (m) RETURN m"
""")
    with pytest.raises(ArchConfigError, match="duplicate custom policy name"):
        load_arch_config(tmp_path)


def test_custom_collides_with_builtin(tmp_path: Path):
    _write(tmp_path, """
[[policies.custom]]
name          = "import_cycles"
count_cypher  = "MATCH (n) RETURN count(n) AS v"
sample_cypher = "MATCH (n) RETURN n"
""")
    with pytest.raises(ArchConfigError, match="collides with a built-in"):
        load_arch_config(tmp_path)


def test_custom_collides_with_orphan_detection_builtin(tmp_path: Path):
    _write(tmp_path, """
[[policies.custom]]
name          = "orphan_detection"
count_cypher  = "MATCH (n) RETURN count(n) AS v"
sample_cypher = "MATCH (n) RETURN n"
""")
    with pytest.raises(ArchConfigError, match="collides with a built-in"):
        load_arch_config(tmp_path)


def test_custom_empty_count_cypher_rejected(tmp_path: Path):
    _write(tmp_path, """
[[policies.custom]]
name          = "bad"
count_cypher  = ""
sample_cypher = "MATCH (n) RETURN n"
""")
    with pytest.raises(ArchConfigError, match="count_cypher must be a non-empty string"):
        load_arch_config(tmp_path)


def test_custom_missing_sample_cypher(tmp_path: Path):
    _write(tmp_path, """
[[policies.custom]]
name          = "bad"
count_cypher  = "MATCH (n) RETURN count(n) AS v"
""")
    with pytest.raises(ArchConfigError, match="sample_cypher"):
        load_arch_config(tmp_path)


# ── Orphan detection ──────────────────────────────────────────


def test_orphan_detection_defaults(tmp_path: Path):
    _write(tmp_path, "")
    cfg = load_arch_config(tmp_path)
    assert cfg.orphan_detection.enabled is True
    assert cfg.orphan_detection.path_prefix == ""
    assert cfg.orphan_detection.kinds == ["function", "class", "atom", "endpoint"]


def test_orphan_detection_disabled(tmp_path: Path):
    _write(tmp_path, """
[policies.orphan_detection]
enabled = false
""")
    cfg = load_arch_config(tmp_path)
    assert cfg.orphan_detection.enabled is False


def test_orphan_detection_custom_prefix(tmp_path: Path):
    _write(tmp_path, """
[policies.orphan_detection]
path_prefix = "src/core/"
""")
    cfg = load_arch_config(tmp_path)
    assert cfg.orphan_detection.path_prefix == "src/core/"


def test_orphan_detection_custom_kinds(tmp_path: Path):
    _write(tmp_path, """
[policies.orphan_detection]
kinds = ["function", "class"]
""")
    cfg = load_arch_config(tmp_path)
    assert cfg.orphan_detection.kinds == ["function", "class"]


def test_orphan_detection_invalid_kind_rejected(tmp_path: Path):
    _write(tmp_path, """
[policies.orphan_detection]
kinds = ["bogus"]
""")
    with pytest.raises(ArchConfigError, match="is not valid"):
        load_arch_config(tmp_path)


def test_orphan_detection_empty_kinds_rejected(tmp_path: Path):
    _write(tmp_path, """
[policies.orphan_detection]
kinds = []
""")
    with pytest.raises(ArchConfigError, match="must not be empty"):
        load_arch_config(tmp_path)


# ── Malformed input ─────────────────────────────────────────


def test_malformed_toml(tmp_path: Path):
    _write(tmp_path, "[[[not valid")
    with pytest.raises(ArchConfigError, match="Malformed TOML"):
        load_arch_config(tmp_path)


def test_policies_must_be_table(tmp_path: Path):
    _write(tmp_path, "policies = 'wrong'\n")
    with pytest.raises(ArchConfigError, match=r"\[policies\] must be a table"):
        load_arch_config(tmp_path)


def test_bool_field_type_checked(tmp_path: Path):
    _write(tmp_path, """
[policies.import_cycles]
enabled = "yes"
""")
    with pytest.raises(ArchConfigError, match="enabled must be a boolean"):
        load_arch_config(tmp_path)
