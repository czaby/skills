---
name: grill-me
description: Interview the user relentlessly about a plan or design until reaching shared understanding, resolving each branch of the decision tree. Supports bare invocation (auto-discovers the lowest-numbered open GitHub issue with the `grilling-needed` label). When applied to a GitHub issue, automatically records findings as a comment and transitions labels (removes `grilling-needed`, `grill-me`, `human`; adds `agent`).
---

# Grill Me

Interview the user relentlessly about every aspect of this plan, design, or issue until we reach a shared understanding. Walk down each branch of the design tree, resolving dependencies between decisions one-by-one. For each question, provide your recommended answer.

Ask the questions one at a time.

If a question can be answered by exploring the codebase, explore the codebase instead (source-first per AGENTS.md).

## Bare `/grill-me` Invocation (Auto-Discovery Mode)

When the user invokes `/grill-me` with **no arguments, parameters, or issue references** at all (i.e., the bare command), automatically discover and grill a GitHub issue using this process:

1. Use the GitHub MCP server (`grok_com_github`) to search for open issues that have the `grilling-needed` label.
   - First call `search_tool` to discover the correct tool name and schema for listing/searching issues with labels.
   - Then use the appropriate `use_tool` call.

2. From the results, select the issue with the **smallest issue number** (lowest numeric ID). This acts as a simple FIFO queue when multiple items need grilling.

3. Fetch the full details of the selected issue (title, body, and recent/relevant comments).

4. Treat that issue's content exactly as if the user had explicitly said `/grill-me #NNN`. Proceed with the grilling process described in the sections below.

If no issues carrying the `grilling-needed` label are found, clearly inform the user and ask what they would like to grill instead.

This mode turns `/grill-me` into a convenient way to pull the next design/plan that needs stress-testing from the issue tracker.

## When the Subject is a GitHub Issue

If the user invokes `/grill-me` while referencing a specific GitHub issue — for example by saying `/grill-me #123`, "grill the plan in issue 45", providing an issue URL, pasting issue content, **or via bare auto-discovery** (see the section above) — treat the issue's body, comments, and linked artifacts as the primary thing being grilled.

- Use the GitHub MCP server (`grok_com_github`) when needed to fetch the latest state of the issue.
- Keep the grilling focused on the content and decisions captured in that issue.

### Conclusion Protocol for GitHub Issues (Mandatory)

When the user signals that the grilling session has reached a satisfactory conclusion — for example by saying "we're done", "conclude the grill", "lock it in", "shared understanding achieved", or otherwise indicating that the decision tree has been sufficiently explored and resolved — you **must** perform the following steps before ending the grill-me session:

1. **Produce a clear written summary of the findings** (in your final response before the tool calls):
   - Key decisions made and their rationale
   - Branches of the decision tree that were explored and how they were resolved
   - Any remaining open risks, assumptions, dependencies, or follow-up questions
   - Recommended next steps (e.g. "Ready to be broken into AFK slices with /to-issues", "Ready for implementation", specific risks to mitigate, etc.)

2. **Record the findings in the GitHub issue**:
   - First, call `search_tool` (from the available tools) with an appropriate query to discover the exact tool names and input schemas for the `grok_com_github` MCP server (especially tools related to adding comments and updating issue labels).
   - After obtaining the schemas, use `use_tool` to:
     - Post the findings summary as a new comment on the issue. Use a clear, consistent format with a heading such as:
       ```
       ## Grill Session Findings — YYYY-MM-DD

       [Your structured summary here]
       ```
     - Update the issue's labels in a single operation if possible:
       - Remove the `grill-me` label (if present)
       - Remove the `grilling-needed` label (if present)
       - Remove the `human` label (if present)
       - Add the `agent` label (if not already present)

3. **Confirm the actions** to the user:
   - Tell them the comment was posted (include the direct link if the tool returns one).
   - List the exact label changes that were made.
   - Note that the issue is now eligible for autonomous AFK work (via the `agent` label).

This step is critical for the overall workflow: a successful grill turns human-intensive design work into clean, agent-ready work for the AFK system.

When the grill was started via bare auto-discovery (by the `grilling-needed` label), removing that label as part of the transition is especially important so the issue is no longer considered "needs grilling."

Do not skip the label transition or the comment posting when the subject of the grill is (or was derived from) a GitHub issue.
