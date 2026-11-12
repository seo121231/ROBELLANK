---
name: discord.py group command removal
description: Behavior of discord.py's nested slash-command group mutation API.
---

`app_commands.Group.remove_command(name)` may remove a child from the group's internal mapping while returning `None`, despite the method's documented and annotated return value. Retrieve the command with `get_command(name)` before removing it.

**Why:** The installed discord.py version exhibited this mismatch while reorganizing nested slash commands; relying on the return value silently loses access to the command object.

**How to apply:** When moving or renaming a command inside an `app_commands.Group`, fetch it first, remove it by its old name, then update and re-add the same command object.
