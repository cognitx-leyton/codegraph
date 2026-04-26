"""Tests for :mod:`codegraph.docker_setup`.

Pure-detection module — every external call (subprocess, /etc/os-release,
platform.system) is mocked. No Docker required to run these tests.
"""
from __future__ import annotations

import subprocess

import pytest

from codegraph import docker_setup
from codegraph.docker_setup import (
    DockerStatus,
    OsInfo,
    _parse_docker_version,
    _parse_os_release,
    check_docker_installed,
    detect_os,
    suggest_daemon_start,
    suggest_docker_install,
    suggest_docker_update,
)


# ── _parse_docker_version ───────────────────────────────────


@pytest.mark.parametrize(
    "stdout,expected",
    [
        ("Docker version 24.0.7, build afdd53b\n", (24, 0, 7)),
        ("Docker version 20.10.21, build baeda1f", (20, 10, 21)),
        ("Docker version 27.3.1, build ce12230", (27, 3, 1)),
        ("Docker version 19.03.0-rc1, build f8e123abc", (19, 3, 0)),
    ],
)
def test_parse_docker_version_known_outputs(stdout, expected):
    assert _parse_docker_version(stdout) == expected


@pytest.mark.parametrize("stdout", [
    "",
    "garbage output",
    "Docker version unknown",
])
def test_parse_docker_version_handles_garbage(stdout):
    """Empty / unparseable outputs return None.

    Note: the regex isn't Docker-specific (matches any ``version N.N.N``).
    Callers establish that the output came from `docker` via
    ``shutil.which("docker")`` first.
    """
    assert _parse_docker_version(stdout) is None


# ── _parse_os_release ───────────────────────────────────────


def test_parse_os_release_ubuntu():
    content = """\
NAME="Ubuntu"
VERSION="24.04 LTS (Noble Numbat)"
ID=ubuntu
VERSION_ID="24.04"
"""
    assert _parse_os_release(content) == ("ubuntu", "24.04")


def test_parse_os_release_debian():
    content = """\
PRETTY_NAME="Debian GNU/Linux 12 (bookworm)"
ID=debian
VERSION_ID="12"
"""
    assert _parse_os_release(content) == ("debian", "12")


def test_parse_os_release_fedora():
    content = """\
NAME=Fedora Linux
VERSION="39 (Workstation Edition)"
ID=fedora
VERSION_ID=39
"""
    assert _parse_os_release(content) == ("fedora", "39")


def test_parse_os_release_arch():
    content = """\
NAME="Arch Linux"
ID=arch
ID_LIKE=archlinux
"""
    distro, version = _parse_os_release(content)
    assert distro == "arch"
    assert version is None  # Arch is rolling, no VERSION_ID


def test_parse_os_release_handles_missing_keys():
    assert _parse_os_release("") == (None, None)
    assert _parse_os_release("# only a comment\n") == (None, None)


def test_parse_os_release_lowercases_id():
    content = "ID=Ubuntu\nVERSION_ID=22.04\n"
    assert _parse_os_release(content) == ("ubuntu", "22.04")


# ── detect_os ───────────────────────────────────────────────


def test_detect_os_linux_with_fake_release(monkeypatch, tmp_path):
    """Linux with a synthetic /etc/os-release pointed at a tmp file."""
    fake_release = tmp_path / "os-release"
    fake_release.write_text('ID=ubuntu\nVERSION_ID="22.04"\n')

    monkeypatch.setattr("platform.system", lambda: "Linux")
    # Patch the Path symbol used inside detect_os so any Path("/etc/os-release")
    # returns our tmp file. Other Path() call sites (none in detect_os) are
    # unaffected because detect_os only constructs that one path.
    real_path = docker_setup.Path

    def _patched_path(p, *a, **kw):
        if str(p) == "/etc/os-release":
            return fake_release
        return real_path(p, *a, **kw)

    monkeypatch.setattr(docker_setup, "Path", _patched_path)

    info = detect_os()
    assert info.family == "linux"
    assert info.distro == "ubuntu"
    assert info.distro_version == "22.04"


def test_detect_os_linux_no_os_release(monkeypatch, tmp_path):
    """Linux without /etc/os-release returns family='linux' with no distro info."""
    missing = tmp_path / "does-not-exist"  # NOT created
    monkeypatch.setattr("platform.system", lambda: "Linux")

    real_path = docker_setup.Path

    def _patched_path(p, *a, **kw):
        if str(p) == "/etc/os-release":
            return missing
        return real_path(p, *a, **kw)

    monkeypatch.setattr(docker_setup, "Path", _patched_path)

    info = detect_os()
    assert info.family == "linux"
    assert info.distro is None


def test_detect_os_darwin(monkeypatch):
    monkeypatch.setattr("platform.system", lambda: "Darwin")
    monkeypatch.setattr("platform.mac_ver", lambda: ("14.5", ("", "", ""), ""))
    info = detect_os()
    assert info.family == "darwin"
    assert info.distro == "macos"
    assert info.distro_version == "14.5"


def test_detect_os_windows(monkeypatch):
    monkeypatch.setattr("platform.system", lambda: "Windows")
    monkeypatch.setattr("platform.version", lambda: "10.0.22631")
    info = detect_os()
    assert info.family == "windows"
    assert info.distro == "windows"


# ── check_docker_installed ──────────────────────────────────


def test_check_docker_installed_missing_binary(monkeypatch):
    """which() returns None → installed=False."""
    monkeypatch.setattr("shutil.which", lambda name: None)
    status = check_docker_installed()
    assert status.installed is False
    assert status.daemon_running is False


def test_check_docker_installed_running_modern(monkeypatch):
    """Modern Docker (24.x) installed and daemon running → all true, no update."""
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/docker")

    def fake_run(cmd, **kwargs):
        if cmd[:2] == ["docker", "--version"]:
            return subprocess.CompletedProcess(
                cmd, 0, stdout="Docker version 24.0.7, build afdd53b\n", stderr="",
            )
        if cmd[:2] == ["docker", "info"]:
            return subprocess.CompletedProcess(cmd, 0, stdout=b"", stderr=b"")
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr("subprocess.run", fake_run)
    status = check_docker_installed()
    assert status.installed is True
    assert status.version == (24, 0, 7)
    assert status.daemon_running is True
    assert status.needs_update is False


def test_check_docker_installed_old_version_flags_update(monkeypatch):
    """Docker 19.x is below the recommended 20.10 baseline → needs_update=True."""
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/docker")

    def fake_run(cmd, **kwargs):
        if cmd[:2] == ["docker", "--version"]:
            return subprocess.CompletedProcess(
                cmd, 0, stdout="Docker version 19.03.12, build 48a66213fe\n", stderr="",
            )
        if cmd[:2] == ["docker", "info"]:
            return subprocess.CompletedProcess(cmd, 0, stdout=b"", stderr=b"")
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr("subprocess.run", fake_run)
    status = check_docker_installed()
    assert status.installed is True
    assert status.version == (19, 3, 12)
    assert status.needs_update is True


def test_check_docker_installed_daemon_down(monkeypatch):
    """`docker --version` works but `docker info` fails → installed=True, daemon_running=False."""
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/docker")

    def fake_run(cmd, **kwargs):
        if cmd[:2] == ["docker", "--version"]:
            return subprocess.CompletedProcess(
                cmd, 0, stdout="Docker version 24.0.7, build afdd53b\n", stderr="",
            )
        if cmd[:2] == ["docker", "info"]:
            return subprocess.CompletedProcess(
                cmd, 1, stdout=b"", stderr=b"Cannot connect to the Docker daemon",
            )
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr("subprocess.run", fake_run)
    status = check_docker_installed()
    assert status.installed is True
    assert status.daemon_running is False


def test_check_docker_installed_version_command_fails(monkeypatch):
    """`docker --version` exits non-zero → treat as not installed."""
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/docker")

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 127, stdout="", stderr="not found")

    monkeypatch.setattr("subprocess.run", fake_run)
    status = check_docker_installed()
    assert status.installed is False


# ── suggest_docker_install ──────────────────────────────────


@pytest.mark.parametrize("distro,expected_substring", [
    ("ubuntu", "get.docker.com"),
    ("debian", "get.docker.com"),
    ("fedora", "dnf"),
    ("rhel", "dnf"),
    ("arch", "pacman"),
    ("manjaro", "pacman"),
    ("opensuse", "zypper"),
])
def test_suggest_docker_install_per_linux_distro(distro, expected_substring):
    info = OsInfo(family="linux", distro=distro)
    assert expected_substring in suggest_docker_install(info)


def test_suggest_docker_install_unknown_linux_falls_back_to_generic():
    info = OsInfo(family="linux", distro="exotic-distro")
    text = suggest_docker_install(info)
    assert "https://docs.docker.com/engine/install/" in text


def test_suggest_docker_install_macos():
    info = OsInfo(family="darwin", distro="macos")
    text = suggest_docker_install(info)
    assert "brew install --cask docker" in text


def test_suggest_docker_install_windows():
    info = OsInfo(family="windows", distro="windows")
    text = suggest_docker_install(info)
    assert "winget install" in text
    assert "Docker.DockerDesktop" in text


# ── suggest_docker_update ───────────────────────────────────


def test_suggest_docker_update_includes_current_version():
    info = OsInfo(family="linux", distro="ubuntu")
    text = suggest_docker_update(info, (19, 3, 12))
    assert "19.3.12" in text
    assert "20.10" in text


def test_suggest_docker_update_macos_uses_brew():
    info = OsInfo(family="darwin", distro="macos")
    text = suggest_docker_update(info, (19, 3, 0))
    assert "brew upgrade --cask docker" in text


# ── suggest_daemon_start ────────────────────────────────────


def test_suggest_daemon_start_linux():
    text = suggest_daemon_start(OsInfo(family="linux"))
    assert "systemctl start docker" in text


def test_suggest_daemon_start_macos():
    text = suggest_daemon_start(OsInfo(family="darwin"))
    assert "open -a Docker" in text


def test_suggest_daemon_start_windows():
    text = suggest_daemon_start(OsInfo(family="windows"))
    assert "Docker Desktop" in text
