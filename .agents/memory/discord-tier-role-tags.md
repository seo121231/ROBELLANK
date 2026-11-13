---
name: Discord tier role tags
description: The bank reads role tiers from square-bracket tags with case-sensitive VIP spelling.
---

Read a bracketed tag in a Discord role name to determine the bank tier. English tags are `[bronze]`, `[silver]`, `[gold]`, `[platinum]`, `[ace]`, and `[VIP]`; the first five are lowercase and VIP is uppercase. Korean tier tags are also supported.

**Why:** The user specified that tier labels are bracketed and that every tier before VIP is lowercase while VIP is uppercase.

**How to apply:** When changing tier detection or role aliases, parse bracket contents case-sensitively and prefer them over role IDs. Keep non-bracket fallback behavior only for legacy roles without bracket tags.
