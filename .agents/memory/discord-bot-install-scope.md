---
name: Discord bot installation scope
description: Distinguishes slash-command installation from installing the bot account into a guild.
---

The application's Guild Install configuration must include both `bot` and `applications.commands`. `applications.commands` alone can register slash commands without adding the bot account to the server.

**Why:** The bot can sync guild commands while its gateway guild list is empty, and it cannot look up a member's roles through the guild API. In that state, the tier parser may be correct while the command still falls back to a default tier.

**How to apply:** When role lookup fails, check Developer Portal → Installation → Guild Install scopes and confirm the bot account is actually in the target server before changing tier parsing. Then verify the live member roles and run the tier command again.
