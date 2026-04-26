"""Interactive REPL for codegraph.

Entered when ``codegraph`` is invoked without a subcommand, or via
``codegraph repl``. Built on top of the ``ReplSkin`` vendored from
cli-anything. Stateful: remembers the current repo and Neo4j connection
across invocations via :class:`codegraph.session.Session`.

Commands (type ``help`` in the REPL to see this list at runtime):

    help                     Show this command list
    status                   Print current repo + connection
    repo <path>              Set the current repo (for validate/index)
    connect [uri] [user]     Connect to Neo4j; prompts for password
    index [--no-wipe]        Index the current repo
    validate                 Run the validation suite
    query <cypher...>        Run a Cypher query
    schema                   Print the graph schema (node labels + edge types)
    last                     Show the last query and its row count
    clear                    Clear the screen
    save                     Persist session state to disk now
    quit / exit              Leave the REPL
"""
from __future__ import annotations

import shlex
import sys
from getpass import getpass
from pathlib import Path
from typing import Optional

from neo4j import GraphDatabase

from .session import Session
from .utils.repl_skin import ReplSkin


# ── Command registry for help / dispatch ─────────────────────────────

_COMMANDS: dict[str, str] = {
    "help":                  "Show this command list",
    "status":                "Print current repo + connection",
    "repo <path>":           "Set the current repo (for validate/index)",
    "connect [uri] [user]":  "Connect to Neo4j; prompts for password",
    "index":                 "Index the current repo (--no-wipe to keep data, --since <ref> for incremental)",
    "validate":              "Run the validation suite on the current repo",
    "query <cypher>":        "Run a Cypher query (wrap multi-word args in quotes)",
    "schema":                "Print the graph schema (node labels + edge types)",
    "last":                  "Show the last query run this session",
    "clear":                 "Clear the screen",
    "save":                  "Persist session state to disk now",
    "quit / exit":           "Leave the REPL",
}

_VERSION = "0.1.0"


# ── Entry point ──────────────────────────────────────────────────────

def run_repl(
    *,
    repo: Optional[Path] = None,
    uri: Optional[str] = None,
    user: Optional[str] = None,
    password: Optional[str] = None,
) -> int:
    """Run the interactive REPL until the user quits.

    Any arguments override values loaded from the persisted session. Returns
    a shell exit code (0 on clean exit, non-zero only if startup fails).
    """
    skin = ReplSkin("codegraph", version=_VERSION)
    session = Session.load()

    # Apply overrides from the CLI layer
    if repo is not None:
        session.set_repo(str(repo))
    if uri is not None:
        session.uri = uri
    if user is not None:
        session.user = user
    if password is not None:
        session.password = password

    skin.print_banner()
    skin.status_block(session.summary(), title="Session")
    print()

    pt_session = skin.create_prompt_session()  # None if prompt_toolkit missing

    while True:
        try:
            repo_label = Path(session.repo).name if session.repo else ""
            line = skin.get_input(
                pt_session,
                project_name=repo_label,
                modified=False,
            )
        except (EOFError, KeyboardInterrupt):
            print()
            skin.print_goodbye()
            session.save()
            return 0

        if not line:
            continue

        try:
            cmd, *args = shlex.split(line)
        except ValueError as e:
            skin.error(f"Parse error: {e}")
            continue

        cmd = cmd.lower()
        try:
            if cmd in ("quit", "exit", "q"):
                session.save()
                skin.print_goodbye()
                return 0
            elif cmd == "help":
                skin.help(_COMMANDS)
            elif cmd == "status":
                skin.status_block(session.summary(), title="Session")
                if session.last_index_stats:
                    skin.section("Last index stats")
                    skin.status_block(
                        {k: str(v) for k, v in session.last_index_stats.items()},
                    )
                print()
            elif cmd == "repo":
                _cmd_repo(skin, session, args)
            elif cmd == "connect":
                _cmd_connect(skin, session, args)
            elif cmd == "index":
                _cmd_index(skin, session, args)
            elif cmd == "validate":
                _cmd_validate(skin, session)
            elif cmd == "query":
                _cmd_query(skin, session, args, raw_line=line)
            elif cmd == "schema":
                _cmd_schema(skin, session)
            elif cmd == "last":
                _cmd_last(skin, session)
            elif cmd == "clear":
                # ANSI clear-and-home; no shell invocation.
                sys.stdout.write("\033[2J\033[H")
                sys.stdout.flush()
            elif cmd == "save":
                session.save()
                skin.success("Session saved")
            else:
                skin.error(f"Unknown command: {cmd!r}. Type `help` for the list.")
        except Exception as e:  # noqa: BLE001
            # REPL should survive any single-command failure.
            skin.error(f"{type(e).__name__}: {e}")


# ── Individual command handlers ──────────────────────────────────────

def _cmd_repo(skin: ReplSkin, session: Session, args: list[str]) -> None:
    if not args:
        skin.hint(f"Usage: repo <path>    (current: {session.repo or '(none)'})")
        return
    path = Path(args[0]).expanduser().resolve()
    if not path.exists() or not path.is_dir():
        skin.error(f"Not a directory: {path}")
        return
    session.set_repo(str(path))
    skin.success(f"Repo set to {path}")


def _cmd_connect(skin: ReplSkin, session: Session, args: list[str]) -> None:
    uri = args[0] if len(args) > 0 else session.uri or "bolt://localhost:7688"
    user = args[1] if len(args) > 1 else session.user or "neo4j"
    password = session.password or getpass(f"Password for {user}@{uri}: ")

    skin.info(f"Connecting to {uri} as {user}...")
    try:
        driver = GraphDatabase.driver(uri, auth=(user, password))
        driver.verify_connectivity()
        driver.close()
    except Exception as e:  # noqa: BLE001
        skin.error(f"Connection failed: {e}")
        return

    session.set_connection(uri, user, password)
    skin.success(f"Connected to {uri}")


def _cmd_index(skin: ReplSkin, session: Session, args: list[str]) -> None:
    if not session.repo:
        skin.error("No repo set. Run `repo <path>` first.")
        return
    if not session.uri:
        skin.error("Not connected to Neo4j. Run `connect` first.")
        return

    wipe = "--no-wipe" not in args

    since = None
    if "--since" in args:
        idx = args.index("--since")
        if idx + 1 < len(args):
            since = args[idx + 1]

    # Dynamically import to keep REPL startup fast
    from .cli import _run_index  # type: ignore[attr-defined]

    skin.info(f"Indexing {session.repo}" + (" (wiping first)" if wipe else ""))
    try:
        stats = _run_index(
            repo=Path(session.repo),
            packages=None,
            wipe=wipe,
            uri=session.uri,
            user=session.user or "neo4j",
            password=session.password or "",
            skip_ownership=False,
            since=since,
        )
        session.last_index_stats = stats
        skin.success("Index complete.")
        skin.status_block({k: str(v) for k, v in stats.items()})
    except Exception as e:  # noqa: BLE001
        skin.error(f"Index failed: {e}")


def _cmd_validate(skin: ReplSkin, session: Session) -> None:
    if not session.repo:
        skin.error("No repo set. Run `repo <path>` first.")
        return
    if not session.uri:
        skin.error("Not connected to Neo4j. Run `connect` first.")
        return

    from .validate import run_validation

    report = run_validation(
        session.uri,
        session.user or "neo4j",
        session.password or "",
        Path(session.repo),
        console=None,  # run_validation tolerates None
    )
    if report.ok:
        skin.success("Validation passed")
    else:
        skin.error("Validation failed — see report above")


def _cmd_query(skin: ReplSkin, session: Session, args: list[str], raw_line: str) -> None:
    if not session.uri:
        skin.error("Not connected to Neo4j. Run `connect` first.")
        return
    # Accept both `query "MATCH ..."` and `query MATCH ...` (rest of line)
    cypher = " ".join(args) if len(args) > 1 else (args[0] if args else "")
    if not cypher:
        cypher = raw_line.split(" ", 1)[1] if " " in raw_line else ""
    if not cypher:
        skin.hint("Usage: query <cypher>")
        return

    session.last_query = cypher
    try:
        driver = GraphDatabase.driver(
            session.uri,
            auth=(session.user or "neo4j", session.password or ""),
        )
        with driver.session() as s:
            rows = list(s.run(cypher))
        driver.close()
    except Exception as e:  # noqa: BLE001
        skin.error(f"Query failed: {e}")
        return

    if not rows:
        skin.hint("(no rows)")
        return

    headers = list(rows[0].keys())
    body = [[str(r.get(h, "")) for h in headers] for r in rows[:50]]
    skin.table(headers, body)
    skin.hint(f"{len(rows)} row(s)" + (" — showing first 50" if len(rows) > 50 else ""))


def _cmd_schema(skin: ReplSkin, session: Session) -> None:
    if not session.uri:
        skin.error("Not connected to Neo4j. Run `connect` first.")
        return
    try:
        driver = GraphDatabase.driver(
            session.uri,
            auth=(session.user or "neo4j", session.password or ""),
        )
        with driver.session() as s:
            labels = [
                r["label"]
                for r in s.run("CALL db.labels() YIELD label RETURN label ORDER BY label")
            ]
            types = [
                r["relationshipType"]
                for r in s.run(
                    "CALL db.relationshipTypes() YIELD relationshipType "
                    "RETURN relationshipType ORDER BY relationshipType"
                )
            ]
        driver.close()
    except Exception as e:  # noqa: BLE001
        skin.error(f"Schema fetch failed: {e}")
        return

    skin.section("Node labels")
    for label in labels:
        print(f"    {label}")
    skin.section("Edge types")
    for t in types:
        print(f"    {t}")
    print()


def _cmd_last(skin: ReplSkin, session: Session) -> None:
    if not session.last_query:
        skin.hint("No query yet this session.")
        return
    skin.section("Last query")
    print(f"    {session.last_query}")
    print()
