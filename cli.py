"""Standalone CLI entry point for ``hermes relatedb-memory`` (discovered without importing ``__init__.py``)."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

# Hermes loads this file from the plugin directory without putting that directory on
# sys.path, so make the bundled ``relatedb_memory`` package importable.
_PLUGIN_DIR = str(Path(__file__).resolve().parent)
if _PLUGIN_DIR not in sys.path:
    sys.path.append(_PLUGIN_DIR)


def _resolve_store_path(raw_path: str | None) -> Path:
    if raw_path:
        return Path(raw_path).expanduser().resolve()
    from relatedb_memory.config import resolve_config

    home = os.environ.get("HERMES_HOME") or str(Path.home() / ".hermes")
    return resolve_config(home).db_path


def _detect_codec(store_path: Path) -> str:
    manifest = store_path / "manifest.json"
    if manifest.is_file():
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("codec"):
                return str(data["codec"])
        except Exception:
            pass
    return "rl"


def _cmd_init_diffable(args: argparse.Namespace) -> int:
    store_path = Path(args.path or "./memory").expanduser().resolve()
    if store_path.exists() and any(store_path.iterdir()):
        if not (store_path / "manifest.json").exists():
            print(json.dumps({"error": f"Target directory is not empty: {store_path}"}), file=sys.stderr)
            return 1
    else:
        subprocess.run(
            ["relate", "--database", str(store_path), "--snapshot-format", "json", "-c", "RETURN 1"],
            check=True,
            capture_output=True,
            text=True,
        )

    cwd = Path.cwd()
    git_root_proc = subprocess.run(
        ["git", "-C", str(cwd), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
    )
    repo_root = Path(git_root_proc.stdout.strip()) if git_root_proc.returncode == 0 else cwd

    attrs_path = repo_root / ".gitattributes"
    existing_attrs = attrs_path.read_text(encoding="utf-8") if attrs_path.is_file() else ""
    lines_to_add = [
        line
        for line in ("graph.json diff=relate-json", "*/graph.json diff=relate-json")
        if line not in existing_attrs
    ]
    if lines_to_add:
        prefix = "\n" if existing_attrs and not existing_attrs.endswith("\n") else ""
        attrs_path.write_text(existing_attrs + prefix + "\n".join(lines_to_add) + "\n", encoding="utf-8")

    if git_root_proc.returncode == 0:
        subprocess.run(
            ["git", "-C", str(repo_root), "config", "diff.relate-json.textconv", "jq ."],
            check=True,
            capture_output=True,
            text=True,
        )

    print(
        json.dumps(
            {
                "path": str(store_path),
                "codec": "json",
                "gitattributes": str(attrs_path),
                "textconv": "jq .",
            }
        )
    )
    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    import relate

    store_path = _resolve_store_path(args.path)
    codec = _detect_codec(store_path)
    conn = relate.connect(str(store_path), read_only=True)
    try:
        nodes = list(conn.execute("MATCH (n) RETURN count(n) AS c"))[0]["c"]
        rels = list(conn.execute("MATCH ()-[r]->() RETURN count(r) AS c"))[0]["c"]
        active_facts = list(conn.execute("MATCH (f:Fact) WHERE f.closedAt IS NULL RETURN count(f) AS c"))[0]["c"]
        closed_facts = list(conn.execute("MATCH (f:Fact) WHERE f.closedAt IS NOT NULL RETURN count(f) AS c"))[0]["c"]
    finally:
        conn.close()

    print(
        json.dumps(
            {
                "path": str(store_path),
                "codec": codec,
                "nodes": int(nodes),
                "relationships": int(rels),
                "active_facts": int(active_facts),
                "closed_facts": int(closed_facts),
            }
        )
    )
    return 0


def _cmd_verify(args: argparse.Namespace) -> int:
    import relate

    store_path = _resolve_store_path(args.path)
    conn = relate.connect(str(store_path), read_only=True)
    try:
        violations = list(
            conn.execute(
                "MATCH (f:Fact) WHERE f.closedAt IS NULL AND f.slot IS NOT NULL "
                "WITH f.slot AS slot, count(*) AS current WHERE current > 1 "
                "RETURN slot, current"
            )
        )
    finally:
        conn.close()

    ok = len(violations) == 0
    print(json.dumps({"ok": ok, "violations": violations}))
    return 0 if ok else 1


def _cmd_mcp(args: argparse.Namespace) -> int:
    store_path = _resolve_store_path(args.path)
    cmd_args = ["serve", "--mcp", "stdio", "--database", str(store_path)]
    if args.read_only:
        cmd_args.append("--read-only=live")
    payload = {"command": "relate", "args": cmd_args}
    if getattr(args, "launch", False):
        return subprocess.run(["relate", *cmd_args], check=False).returncode
    print(json.dumps(payload))
    return 0


def _cmd_cypher(args: argparse.Namespace) -> int:
    import relate
    from relatedb_memory.provider import _validate_read_only_cypher

    store_path = _resolve_store_path(args.path)
    _validate_read_only_cypher(args.query)
    conn = relate.connect(str(store_path), read_only=True)
    try:
        rows = list(conn.execute(args.query))
    finally:
        conn.close()
    print(json.dumps({"rows": rows}, default=str))
    return 0


def register_cli(parser: argparse.ArgumentParser) -> None:
    """Register subcommands onto the ``hermes relatedb-memory`` parser Hermes hands us.

    Hermes looks for a handler named ``<provider>_command``, which is not a valid Python
    name when the provider name has a hyphen, so the dispatcher is set on the parser here.
    """
    parser.set_defaults(func=relatedb_command)
    subparser = parser.add_subparsers(dest="subcommand", required=True)
    p_init = subparser.add_parser("init-diffable", help="Initialize a diffable JSON RelateDB store")
    p_init.add_argument("path", nargs="?", default="./memory", help="Target store directory (default: ./memory)")
    p_init.set_defaults(_handler=_cmd_init_diffable)

    p_status = subparser.add_parser("status", help="Show RelateDB store status and counts")
    p_status.add_argument("--path", default=None, help="Store path override")
    p_status.set_defaults(_handler=_cmd_status)

    p_verify = subparser.add_parser("verify", help="Verify bi-temporal slot-uniqueness invariants")
    p_verify.add_argument("--path", default=None, help="Store path override")
    p_verify.set_defaults(_handler=_cmd_verify)

    p_mcp = subparser.add_parser("mcp", help="Output or launch Relate stdio MCP sidecar configuration")
    p_mcp.add_argument("--path", default=None, help="Store path override")
    p_mcp.add_argument("--read-only", action="store_true", help="Pass --read-only=live to relate serve")
    p_mcp.add_argument("--launch", action="store_true", help="Launch relate serve --mcp stdio directly")
    p_mcp.set_defaults(_handler=_cmd_mcp)

    p_cypher = subparser.add_parser("cypher", help="Run a read-only Cypher query against the store")
    p_cypher.add_argument("query", help="Read-only Cypher query")
    p_cypher.add_argument("--path", default=None, help="Store path override")
    p_cypher.set_defaults(_handler=_cmd_cypher)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hermes relatedb-memory", description="RelateDB memory store CLI")
    register_cli(parser)
    return parser


def relatedb_command(args: argparse.Namespace) -> int:
    handler = getattr(args, "_handler", None)
    if handler is None:
        return 1
    return int(handler(args))


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    return relatedb_command(args)


if __name__ == "__main__":
    raise SystemExit(main())
