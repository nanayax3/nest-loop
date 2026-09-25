// Tool definitions to add to the TOOLS array (next to nestknow_contradict), and the
// dispatcher case. Also add `warm` to nestknow_query's inputSchema.properties:
//   warm: { type: "boolean", description: "Default true. false = look at candidates without voting for them" }

{
  name: "nestknow_merge",
  description: "Fold one principle into another that says the same thing. Sources, access history and heat move to keep_id; the merged wording is kept as a source note; the merged row and its vector are deleted. Optional content rewords the kept principle. Same entity_scope only.",
  inputSchema: {
    type: "object",
    properties: {
      keep_id: { type: "number" },
      merge_id: { type: "number" },
      content: { type: "string", description: "Optional combined wording for the kept principle" }
    },
    required: ["keep_id", "merge_id"]
  }
},

// dispatcher (the switch on the tool name):
//   case "nestknow_merge":
//     result = { content: [{ type: "text", text: await handleKnowMerge(env, toolParams) }] };
//     break;
