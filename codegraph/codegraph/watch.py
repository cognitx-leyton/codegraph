"""File watcher — auto-rebuild the graph on save.

Uses ``watchdog`` (optional ``[watch]`` extra) to watch for file changes and
trigger incremental re-indexing via ``codegraph index <repo> --since HEAD --json``.
Ported from graphify's ``watch.py`` with attribution.
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

_WATCHED_EXTENSIONS: frozenset[str] = frozenset({".py", ".ts", ".tsx"})

_EXCLUDE_DIRS: frozenset[str] = frozenset({
    ".git", "node_modules", ".venv", "__pycache__", ".mypy_cache", ".pytest_cache",
})


def _require_watchdog():
    """Import watchdog or raise a helpful error."""
    try:
        from watchdog.events import FileSystemEventHandler  # noqa: F401
        from watchdog.observers import Observer  # noqa: F401
        from watchdog.observers.polling import PollingObserver  # noqa: F401
    except ImportError as exc:
        raise ImportError(
            "watchdog not installed. Run: pip install 'codegraph[watch]'"
        ) from exc


def _make_handler():
    """Create and return a Handler instance (imports watchdog lazily)."""
    from watchdog.events import FileSystemEventHandler

    class _Handler(FileSystemEventHandler):
        """Collect changed file paths, filtering by extension and excluded dirs."""

        def __init__(self) -> None:
            super().__init__()
            self.changed: set[Path] = set()
            self.last_trigger: float = 0.0
            self.pending: bool = False

        def on_any_event(self, event) -> None:  # noqa: ANN001
            if event.is_directory:
                return
            path = Path(event.src_path)
            if path.suffix.lower() not in _WATCHED_EXTENSIONS:
                return
            if any(part.startswith(".") for part in path.parts):
                return
            if any(part in _EXCLUDE_DIRS for part in path.parts):
                return
            self.last_trigger = time.monotonic()
            self.pending = True
            self.changed.add(path)

    return _Handler()


def _rebuild(
    repo: Path,
    *,
    quiet: bool = True,
    uri: str = "",
    user: str = "",
    password: str = "",
    packages: Optional[list[str]] = None,
) -> bool:
    """Trigger an incremental re-index via subprocess.

    Returns True on success, False on error.
    """
    cmd = [
        sys.executable, "-m", "codegraph.cli", "index", str(repo),
        "--since", "HEAD", "--json",
    ]
    if uri:
        cmd.extend(["--uri", uri])
    if user:
        cmd.extend(["--user", user])
    if password:
        cmd.extend(["--password", password])
    for pkg in (packages or []):
        cmd.extend(["--package", pkg])
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, check=False, timeout=300,
        )
        if result.returncode != 0:
            if not quiet:
                print(f"[codegraph watch] Rebuild failed: {result.stderr.strip()}")
            return False
        return True
    except (OSError, subprocess.SubprocessError) as exc:
        if not quiet:
            print(f"[codegraph watch] Rebuild error: {exc}")
        return False


def watch(
    watch_path: Path,
    *,
    debounce: float = 3.0,
    uri: str = "",
    user: str = "",
    password: str = "",
    packages: Optional[list[str]] = None,
) -> None:
    """Watch *watch_path* for file changes and auto-rebuild the graph.

    Parameters
    ----------
    watch_path:
        Root of the repo to watch.
    debounce:
        Seconds to wait after the last change before triggering a rebuild.
    uri, user, password:
        Neo4j connection params forwarded to ``codegraph index``.
    packages:
        Package filter forwarded to ``codegraph index``.
    """
    _require_watchdog()
    from watchdog.observers import Observer
    from watchdog.observers.polling import PollingObserver

    handler = _make_handler()
    # Use polling observer on macOS — FSEvents can miss rapid saves
    observer = PollingObserver() if sys.platform == "darwin" else Observer()
    observer.schedule(handler, str(watch_path), recursive=True)
    observer.start()

    print(f"[codegraph watch] Watching {watch_path.resolve()} - press Ctrl+C to stop")
    print(f"[codegraph watch] Debounce: {debounce}s")

    try:
        while True:
            time.sleep(0.5)
            if handler.pending and (time.monotonic() - handler.last_trigger) >= debounce:
                handler.pending = False
                batch = list(handler.changed)
                handler.changed.clear()
                print(f"\n[codegraph watch] {len(batch)} file(s) changed - rebuilding...")
                ok = _rebuild(
                    watch_path, quiet=False,
                    uri=uri, user=user, password=password, packages=packages,
                )
                if ok:
                    print("[codegraph watch] Rebuild complete.")
    except KeyboardInterrupt:
        print("\n[codegraph watch] Stopped.")
    finally:
        observer.stop()
        observer.join()


def run_watch(
    *,
    repo: Path,
    debounce: float = 3.0,
    uri: str = "",
    user: str = "",
    password: str = "",
    packages: Optional[list[str]] = None,
) -> int:
    """Entry point called from CLI. Returns exit code 0."""
    watch(
        repo,
        debounce=debounce,
        uri=uri,
        user=user,
        password=password,
        packages=packages,
    )
    return 0
