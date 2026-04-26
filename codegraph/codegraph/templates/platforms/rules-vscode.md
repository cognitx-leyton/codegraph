## codegraph

This project has a codegraph knowledge graph in Neo4j (`bolt://localhost:$NEO4J_BOLT_PORT`).

Rules:
- Before answering architecture or codebase questions, run `codegraph query "MATCH ..."` or read `codegraph-out/GRAPH_REPORT.md`
- Use `codegraph arch-check` to verify architecture conformance
- After structural code changes, run `codegraph index . --since HEAD~1` to update the graph
- For cross-module dependency questions, prefer Cypher queries over grep
