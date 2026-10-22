---
name: .replit configuration validation
description: The workspace requires schema validation when replacing the root .replit configuration.
---

Prepare the complete updated TOML as a temporary workspace file and use `verifyAndReplaceDotReplit` with its absolute path. Direct edits to `.replit` are rejected.

**Why:** The workspace validates Replit configuration before replacement; direct patches fail and can leave the running workflow unchanged.

**How to apply:** When changing workflow commands or other `.replit` settings in this workspace, use the validated replacement flow and then restart the affected workflow.
