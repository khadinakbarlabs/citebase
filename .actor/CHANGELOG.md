# Changelog

## 0.3
- Six stateless tools: get_playbook, audit_site, quote_cost, measure_recommendation_share, next_steps, check_outreach_draft.
- Every tool has a described input schema, a typed output schema, annotations and a plain-language description.
- Works as a Standby MCP server (`/mcp`) and through a plain JSON endpoint (`/run`), which is what mcp.apify.com exposes.
- One-shot run mode with dataset, output and key-value-store schemas.
- Site check refuses private and local addresses, bounds response size and time, and never runs JavaScript.
- Logs one safe line per call (tool, input size, outcome, time); never the content.
