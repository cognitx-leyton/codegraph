"""Docker presence and OS detection helpers for `codegraph init`.

Pure detection — never executes install or upgrade commands. The helpers
return :class:`DockerStatus` and :class:`OsInfo` dataclasses plus OS-aware
suggestion strings the caller (init.py) prints. Auto-running install
would require ``sudo`` on Linux and is too risky to automate.

Usage::

    from codegraph.docker_setup import (
        check_docker_installed, detect_os,
        suggest_docker_install, suggest_docker_update, suggest_daemon_start,
    )

    status = check_docker_installed()
    os_info = detect_os()

    if not status.installed:
        console.print(suggest_docker_install(os_info))
    elif not status.daemon_running:
        console.print(suggest_daemon_start(os_info))
    elif status.needs_update:
        console.print(suggest_docker_update(os_info, status.version))
"""
from __future__ import annotations

import platform
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# Recommended Docker baseline. Older versions miss the v2 ``docker compose``
# plugin and several BuildKit improvements we rely on indirectly through
# the bundled compose file.
_MIN_DOCKER_VERSION: tuple[int, int] = (20, 10)

# `docker info` blocks until the daemon answers — short timeout keeps init
# responsive when Docker Desktop is mid-launch on macOS / Windows.
_DAEMON_PROBE_TIMEOUT_SEC = 5


@dataclass
class DockerStatus:
    """What we learned about the Docker install on this machine."""

    installed: bool
    version: Optional[tuple[int, int, int]] = None
    version_str: Optional[str] = None
    daemon_running: bool = False
    needs_update: bool = False


@dataclass
class OsInfo:
    """Operating system family + distro for OS-aware suggestions."""

    family: str  # "linux" | "darwin" | "windows" | other
    distro: Optional[str] = None  # "ubuntu" | "debian" | "fedora" | "arch" | "macos" | …
    distro_version: Optional[str] = None  # "24.04" | "12" | "39" | …


# ── Docker detection ────────────────────────────────────────────────


def check_docker_installed() -> DockerStatus:
    """Return a :class:`DockerStatus` for the current machine.

    Checks (in order, cheapest first):
      1. ``shutil.which("docker")`` — is the binary on PATH?
      2. ``docker --version`` — version string + numeric tuple.
      3. ``docker info`` (5s timeout) — is the daemon answering?

    If any step fails the status reflects the *closest* truthful answer
    rather than raising.
    """
    if shutil.which("docker") is None:
        return DockerStatus(installed=False)

    try:
        result = subprocess.run(
            ["docker", "--version"],
            capture_output=True, text=True, timeout=_DAEMON_PROBE_TIMEOUT_SEC,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return DockerStatus(installed=False)

    if result.returncode != 0:
        return DockerStatus(installed=False)

    version_str = result.stdout.strip()
    version = _parse_docker_version(version_str)
    needs_update = version is not None and version[:2] < _MIN_DOCKER_VERSION
    daemon_running = _is_docker_daemon_running()

    return DockerStatus(
        installed=True,
        version=version,
        version_str=version_str,
        daemon_running=daemon_running,
        needs_update=needs_update,
    )


def _parse_docker_version(output: str) -> Optional[tuple[int, int, int]]:
    """Pull the (major, minor, patch) tuple out of ``docker --version`` output.

    Example input: ``"Docker version 24.0.7, build afdd53b"``.
    """
    match = re.search(r"version (\d+)\.(\d+)\.(\d+)", output)
    if match is None:
        return None
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


def _is_docker_daemon_running() -> bool:
    """Probe the daemon with ``docker info``.  Returns False on any failure."""
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True, timeout=_DAEMON_PROBE_TIMEOUT_SEC,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


# ── OS detection ────────────────────────────────────────────────────


def detect_os() -> OsInfo:
    """Detect the current OS family and (on Linux) the distro from ``/etc/os-release``."""
    family = platform.system().lower()  # "linux" | "darwin" | "windows"

    if family == "linux":
        os_release = Path("/etc/os-release")
        if os_release.exists():
            try:
                content = os_release.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                return OsInfo(family="linux")
            distro, version = _parse_os_release(content)
            return OsInfo(family="linux", distro=distro, distro_version=version)
        return OsInfo(family="linux")

    if family == "darwin":
        version = platform.mac_ver()[0] or None
        return OsInfo(family="darwin", distro="macos", distro_version=version)

    if family == "windows":
        return OsInfo(family="windows", distro="windows", distro_version=platform.version())

    return OsInfo(family=family)


def _parse_os_release(content: str) -> tuple[Optional[str], Optional[str]]:
    """Extract ``ID`` and ``VERSION_ID`` from ``/etc/os-release`` content."""
    distro: Optional[str] = None
    version: Optional[str] = None
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip().strip('"').strip("'")
        if key.strip() == "ID":
            distro = value.lower()
        elif key.strip() == "VERSION_ID":
            version = value
    return distro, version


# ── Suggestion strings ──────────────────────────────────────────────


def suggest_docker_install(os_info: OsInfo) -> str:
    """OS-aware multi-line install command.  Caller prints it verbatim."""
    if os_info.family == "linux":
        if os_info.distro in {"ubuntu", "debian", "pop", "linuxmint", "elementary"}:
            return (
                "Docker is not installed. Recommended install (Debian/Ubuntu family):\n"
                "  curl -fsSL https://get.docker.com | sh\n"
                "  sudo usermod -aG docker $USER\n"
                "Then log out and back in (or run `newgrp docker`) so your shell sees the group.\n"
                "Reference: https://docs.docker.com/engine/install/"
            )
        if os_info.distro in {"fedora", "rhel", "centos", "rocky", "almalinux"}:
            return (
                "Docker is not installed. Recommended install (Fedora/RHEL family):\n"
                "  sudo dnf -y install dnf-plugins-core\n"
                "  sudo dnf config-manager --add-repo https://download.docker.com/linux/fedora/docker-ce.repo\n"
                "  sudo dnf -y install docker-ce docker-ce-cli containerd.io docker-compose-plugin\n"
                "  sudo systemctl enable --now docker\n"
                "  sudo usermod -aG docker $USER\n"
                "Reference: https://docs.docker.com/engine/install/fedora/"
            )
        if os_info.distro in {"arch", "manjaro", "endeavouros"}:
            return (
                "Docker is not installed. Recommended install (Arch family):\n"
                "  sudo pacman -S --noconfirm docker docker-compose\n"
                "  sudo systemctl enable --now docker.service\n"
                "  sudo usermod -aG docker $USER"
            )
        if os_info.distro in {"opensuse", "opensuse-leap", "opensuse-tumbleweed", "sles"}:
            return (
                "Docker is not installed. Recommended install (openSUSE/SLES):\n"
                "  sudo zypper install -y docker docker-compose\n"
                "  sudo systemctl enable --now docker\n"
                "  sudo usermod -aG docker $USER"
            )
        return (
            "Docker is not installed. Generic Linux instructions:\n"
            "  https://docs.docker.com/engine/install/\n"
            "Or use the convenience script (works on most distros):\n"
            "  curl -fsSL https://get.docker.com | sh"
        )

    if os_info.family == "darwin":
        return (
            "Docker is not installed. Recommended install (macOS):\n"
            "  brew install --cask docker\n"
            "Then launch Docker.app (Applications → Docker) and wait for the whale icon to settle.\n"
            "Or download the installer from https://www.docker.com/products/docker-desktop/"
        )

    if os_info.family == "windows":
        return (
            "Docker is not installed. Recommended install (Windows):\n"
            "  winget install -e --id Docker.DockerDesktop\n"
            "Or download from https://www.docker.com/products/docker-desktop/\n"
            "After install: launch Docker Desktop and wait for it to finish initialising."
        )

    return (
        "Docker is not installed. Find install instructions for your platform at:\n"
        "  https://docs.docker.com/engine/install/"
    )


def suggest_docker_update(os_info: OsInfo, current_version: tuple[int, int, int]) -> str:
    """OS-aware upgrade command when the installed Docker is older than the recommended baseline."""
    cur = ".".join(str(part) for part in current_version)
    rec = ".".join(str(part) for part in _MIN_DOCKER_VERSION) + "+"
    header = f"Docker {cur} is installed, but {rec} is recommended for full `docker compose` v2 support."

    if os_info.family == "linux":
        if os_info.distro in {"ubuntu", "debian", "pop", "linuxmint", "elementary"}:
            return f"{header}\nUpgrade with:\n  sudo apt-get update && sudo apt-get install --only-upgrade docker-ce docker-ce-cli docker-compose-plugin"
        if os_info.distro in {"fedora", "rhel", "centos", "rocky", "almalinux"}:
            return f"{header}\nUpgrade with:\n  sudo dnf upgrade -y docker-ce docker-ce-cli docker-compose-plugin"
        if os_info.distro in {"arch", "manjaro", "endeavouros"}:
            return f"{header}\nUpgrade with:\n  sudo pacman -Syu docker docker-compose"
        if os_info.distro in {"opensuse", "opensuse-leap", "opensuse-tumbleweed", "sles"}:
            return f"{header}\nUpgrade with:\n  sudo zypper update docker docker-compose"
        return f"{header}\nUpgrade via your distro's package manager, or re-run the convenience script:\n  curl -fsSL https://get.docker.com | sh"

    if os_info.family == "darwin":
        return f"{header}\nUpgrade Docker Desktop: open the app and use its built-in upgrade prompt, or run:\n  brew upgrade --cask docker"

    if os_info.family == "windows":
        return f"{header}\nUpgrade Docker Desktop: open the app and use its built-in upgrade prompt, or run:\n  winget upgrade -e --id Docker.DockerDesktop"

    return header


def suggest_daemon_start(os_info: OsInfo) -> str:
    """OS-aware command to start the Docker daemon when it's not running."""
    if os_info.family == "linux":
        return (
            "Docker is installed but the daemon isn't running. Start it with:\n"
            "  sudo systemctl start docker\n"
            "Enable on boot:\n"
            "  sudo systemctl enable docker"
        )
    if os_info.family == "darwin":
        return (
            "Docker is installed but the daemon isn't running. Start Docker Desktop:\n"
            "  open -a Docker\n"
            "Wait for the whale icon in the menu bar to stop animating before re-running init."
        )
    if os_info.family == "windows":
        return (
            "Docker is installed but the daemon isn't running. "
            "Launch Docker Desktop from the Start menu and wait for it to finish initialising "
            "before re-running init."
        )
    return (
        "Docker is installed but the daemon isn't running. "
        "Start it however your platform expects, then re-run init."
    )
