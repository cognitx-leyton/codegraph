"""Tests for the shared-Neo4j helpers in :mod:`codegraph.init`.

Covers :func:`find_existing_neo4j_container`, :func:`start_existing_container`,
:func:`_resolve_neo4j_setup`, and :func:`_preflight_docker`. All Docker calls
mocked at the ``subprocess.run`` level — no Docker required.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from rich.console import Console

from codegraph import init as init_module
from codegraph.docker_setup import DockerStatus, OsInfo
from codegraph.init import (
    InitConfig,
    Neo4jSetup,
    SHARED_CONTAINER_NAME,
    _preflight_docker,
    _resolve_neo4j_setup,
    find_existing_neo4j_container,
    start_existing_container,
)


def _silent_console() -> Console:
    return Console(quiet=True, file=open("/dev/null", "w"))


def _make_config(**overrides) -> InitConfig:
    """Build a default-ish InitConfig the helpers can operate on."""
    base = dict(
        packages=["."],
        cross_pairs=[],
        install_claude=True,
        install_ci=True,
        setup_neo4j=True,
        container_name=SHARED_CONTAINER_NAME,
        install_hooks=False,
        install_platforms=[],
        bolt_port=7687,
        http_port=7474,
    )
    base.update(overrides)
    return InitConfig(**base)


# ── find_existing_neo4j_container ───────────────────────────


def test_find_existing_returns_none_when_docker_missing(monkeypatch):
    def boom(*args, **kwargs):
        raise FileNotFoundError("docker not on PATH")
    monkeypatch.setattr("subprocess.run", boom)
    assert find_existing_neo4j_container("codegraph-neo4j") is None


def test_find_existing_returns_none_when_inspect_fails(monkeypatch):
    """`docker inspect` exiting non-zero (container missing) → None."""
    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="No such object")
    monkeypatch.setattr("subprocess.run", fake_run)
    assert find_existing_neo4j_container("codegraph-neo4j") is None


def test_find_existing_returns_dict_for_running_container(monkeypatch):
    """Happy path: parse the inspect JSON into the canonical dict shape."""
    inspect = {
        "State": {"Status": "running"},
        "Config": {"Image": "neo4j:5.24-community"},
        "NetworkSettings": {
            "Ports": {
                "7687/tcp": [{"HostIp": "0.0.0.0", "HostPort": "7688"}],
                "7474/tcp": [{"HostIp": "0.0.0.0", "HostPort": "7475"}],
            }
        },
    }

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(
            cmd, 0, stdout=json.dumps(inspect), stderr="",
        )
    monkeypatch.setattr("subprocess.run", fake_run)

    result = find_existing_neo4j_container("codegraph-neo4j")
    assert result is not None
    assert result["state"] == "running"
    assert result["image"] == "neo4j:5.24-community"
    assert result["ports"]["bolt"] == 7688
    assert result["ports"]["http"] == 7475


def test_find_existing_handles_stopped_container(monkeypatch):
    """Stopped containers come back with state='exited'."""
    inspect = {
        "State": {"Status": "exited"},
        "Config": {"Image": "neo4j:5.24-community"},
        "NetworkSettings": {"Ports": {}},
    }

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(
            cmd, 0, stdout=json.dumps(inspect), stderr="",
        )
    monkeypatch.setattr("subprocess.run", fake_run)

    result = find_existing_neo4j_container("codegraph-neo4j")
    assert result is not None
    assert result["state"] == "exited"
    # Stopped containers have no published port bindings
    assert result["ports"] == {}


def test_find_existing_handles_garbage_json(monkeypatch):
    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, stdout="not json", stderr="")
    monkeypatch.setattr("subprocess.run", fake_run)
    assert find_existing_neo4j_container("codegraph-neo4j") is None


# ── start_existing_container ────────────────────────────────


def test_start_existing_success(monkeypatch):
    def fake_run(cmd, **kwargs):
        assert cmd == ["docker", "start", "codegraph-neo4j"]
        return subprocess.CompletedProcess(cmd, 0, stdout="codegraph-neo4j\n", stderr="")
    monkeypatch.setattr("subprocess.run", fake_run)
    assert start_existing_container("codegraph-neo4j", _silent_console()) is True


def test_start_existing_failure(monkeypatch):
    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(
            cmd, 1, stdout="", stderr="Error: No such container",
        )
    monkeypatch.setattr("subprocess.run", fake_run)
    assert start_existing_container("codegraph-neo4j", _silent_console()) is False


def test_start_existing_docker_missing(monkeypatch):
    def boom(*args, **kwargs):
        raise FileNotFoundError("no docker")
    monkeypatch.setattr("subprocess.run", boom)
    assert start_existing_container("codegraph-neo4j", _silent_console()) is False


# ── _resolve_neo4j_setup ────────────────────────────────────


def test_resolve_docker_missing(monkeypatch):
    """Docker not installed → DOCKER_MISSING."""
    monkeypatch.setattr(
        init_module, "check_docker_installed",
        lambda: DockerStatus(installed=False),
    )
    config = _make_config()
    setup = _resolve_neo4j_setup(config, _silent_console())
    assert setup == Neo4jSetup.DOCKER_MISSING


def test_resolve_daemon_down(monkeypatch):
    """Docker installed but daemon not running → DAEMON_DOWN."""
    config = _make_config()
    setup = _resolve_neo4j_setup(
        config, _silent_console(),
        docker_status=DockerStatus(installed=True, daemon_running=False),
    )
    assert setup == Neo4jSetup.DAEMON_DOWN


def test_resolve_reuse_running_syncs_ports(monkeypatch):
    """Existing running container → REUSE_RUNNING + config ports updated."""
    monkeypatch.setattr(
        init_module, "find_existing_neo4j_container",
        lambda name: {
            "name": name, "state": "running",
            "image": "neo4j:5.24-community",
            "ports": {"bolt": 7688, "http": 7475},
        },
    )
    config = _make_config(bolt_port=7687, http_port=7474)
    setup = _resolve_neo4j_setup(
        config, _silent_console(),
        docker_status=DockerStatus(installed=True, daemon_running=True),
    )
    assert setup == Neo4jSetup.REUSE_RUNNING
    assert config.bolt_port == 7688  # synced from container
    assert config.http_port == 7475


def test_resolve_reuse_stopped_calls_start(monkeypatch):
    """Existing stopped container → start it, return REUSE_STOPPED."""
    monkeypatch.setattr(
        init_module, "find_existing_neo4j_container",
        lambda name: {
            "name": name, "state": "exited",
            "image": "neo4j:5.24-community",
            "ports": {},  # stopped containers have no port bindings
        },
    )
    started: list[str] = []

    def fake_start(name, console):
        started.append(name)
        return True

    monkeypatch.setattr(init_module, "start_existing_container", fake_start)

    config = _make_config()
    setup = _resolve_neo4j_setup(
        config, _silent_console(),
        docker_status=DockerStatus(installed=True, daemon_running=True),
    )
    assert setup == Neo4jSetup.REUSE_STOPPED
    assert started == ["codegraph-neo4j"]


def test_resolve_start_failed(monkeypatch):
    """Existing stopped container that fails to start → START_FAILED."""
    monkeypatch.setattr(
        init_module, "find_existing_neo4j_container",
        lambda name: {"name": name, "state": "exited", "image": "x", "ports": {}},
    )
    monkeypatch.setattr(
        init_module, "start_existing_container",
        lambda name, console: False,
    )
    config = _make_config()
    setup = _resolve_neo4j_setup(
        config, _silent_console(),
        docker_status=DockerStatus(installed=True, daemon_running=True),
    )
    assert setup == Neo4jSetup.START_FAILED


def test_resolve_create_new_when_no_container_and_ports_free(monkeypatch):
    """No existing container + ports free → CREATE_NEW."""
    monkeypatch.setattr(
        init_module, "find_existing_neo4j_container", lambda name: None,
    )
    monkeypatch.setattr(init_module, "_is_port_in_use", lambda port: False)
    config = _make_config()
    setup = _resolve_neo4j_setup(
        config, _silent_console(),
        docker_status=DockerStatus(installed=True, daemon_running=True),
    )
    assert setup == Neo4jSetup.CREATE_NEW


def test_resolve_port_taken_when_no_container_but_port_busy(monkeypatch):
    """No existing container but bolt port held by something else → PORT_TAKEN."""
    monkeypatch.setattr(
        init_module, "find_existing_neo4j_container", lambda name: None,
    )
    monkeypatch.setattr(init_module, "_is_port_in_use", lambda port: True)
    config = _make_config()
    setup = _resolve_neo4j_setup(
        config, _silent_console(),
        docker_status=DockerStatus(installed=True, daemon_running=True),
    )
    assert setup == Neo4jSetup.PORT_TAKEN


# ── _preflight_docker ───────────────────────────────────────


def test_preflight_returns_none_when_missing(monkeypatch):
    monkeypatch.setattr(
        init_module, "check_docker_installed",
        lambda: DockerStatus(installed=False),
    )
    monkeypatch.setattr(init_module, "detect_os", lambda: OsInfo(family="linux", distro="ubuntu"))
    assert _preflight_docker(_silent_console()) is None


def test_preflight_returns_none_when_daemon_down(monkeypatch):
    monkeypatch.setattr(
        init_module, "check_docker_installed",
        lambda: DockerStatus(installed=True, daemon_running=False, version_str="Docker version 24.0.7"),
    )
    monkeypatch.setattr(init_module, "detect_os", lambda: OsInfo(family="linux"))
    assert _preflight_docker(_silent_console()) is None


def test_preflight_returns_status_when_healthy(monkeypatch):
    healthy = DockerStatus(
        installed=True, version=(24, 0, 7), version_str="Docker version 24.0.7",
        daemon_running=True, needs_update=False,
    )
    monkeypatch.setattr(init_module, "check_docker_installed", lambda: healthy)
    monkeypatch.setattr(init_module, "detect_os", lambda: OsInfo(family="linux"))
    assert _preflight_docker(_silent_console()) == healthy


def test_preflight_warns_but_returns_status_when_stale(monkeypatch):
    """Old Docker still passes preflight (with a warning) — `--update` is a soft nudge."""
    stale = DockerStatus(
        installed=True, version=(19, 3, 0), version_str="Docker version 19.3.0",
        daemon_running=True, needs_update=True,
    )
    monkeypatch.setattr(init_module, "check_docker_installed", lambda: stale)
    monkeypatch.setattr(init_module, "detect_os", lambda: OsInfo(family="linux", distro="ubuntu"))
    assert _preflight_docker(_silent_console()) == stale
