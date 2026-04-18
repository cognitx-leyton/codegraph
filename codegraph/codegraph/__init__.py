"""codegraph — map a TS/TSX codebase into Neo4j with NestJS + React awareness."""
from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("cognitx-codegraph")
except PackageNotFoundError:
    __version__ = "0.0.0-dev"
