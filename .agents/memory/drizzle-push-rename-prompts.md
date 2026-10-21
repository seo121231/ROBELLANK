---
name: Drizzle push rename prompts
description: Handling Drizzle schema pushes that misinterpret a same-type column replacement as a rename.
---

When a schema removes one column and adds another same-type column to the same table in one change, `drizzle-kit push --force` may still stop at an interactive rename/conflict prompt when no TTY is available. Add the new column and index while keeping the old column in the schema, push that additive change, then remove the old column and push again after confirming the dropped data is intentionally obsolete.

**Why:** `--force` approves data-loss statements but does not resolve every column-mapping prompt; combining the changes can block an otherwise safe migration in this non-interactive environment.

**How to apply:** For a replacement field such as a removed identifier and a new display-name field, stage the addition first, verify existing records, then make the removal explicit as a separate schema change.
