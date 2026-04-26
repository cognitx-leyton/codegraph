## codegraph workflow

Use the codegraph knowledge graph (`bolt://localhost:$NEO4J_BOLT_PORT`) for architecture queries.

Steps:
1. Before structural edits, check blast radius: `codegraph query "MATCH (n)-[r]->(m) WHERE n.name = '<symbol>' RETURN type(r), m.name"`
2. After code changes, update the graph: `codegraph index . --since HEAD~1`
3. Verify conformance: `codegraph arch-check`
4. For cross-module dependency questions, prefer Cypher queries over grep
