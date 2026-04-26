// codegraph OpenCode plugin — reminds the assistant about the knowledge graph
// before file-reading tool calls.
//
// Installed by: codegraph install opencode
// Neo4j bolt endpoint: bolt://localhost:$NEO4J_BOLT_PORT

export default {
  name: "codegraph",
  version: "1.0.0",
  hooks: {
    "tool.execute.before": async (ctx) => {
      const readTools = ["read_file", "list_directory", "glob", "grep"];
      if (readTools.includes(ctx.tool)) {
        ctx.messages.push({
          role: "system",
          content:
            "Reminder: this project has a codegraph knowledge graph. " +
            "For architecture questions, prefer `codegraph query` over reading files. " +
            "Read codegraph-out/GRAPH_REPORT.md for a pre-built overview.",
        });
      }
    },
  },
};
