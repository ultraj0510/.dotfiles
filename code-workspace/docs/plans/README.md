# Plans

This directory is the durable plan location declared by `/Users/fujie/code/workspace.toml`.
The same manifest uniquely declares the runtime task directory, archive directory, and lessons file.

Existing locations are kept for history:

- `/Users/fujie/code/docs/superpowers/plans`
- `/Users/fujie/code/.omc/plans`
- `/Users/fujie/code/tasks`
- `/Users/fujie/code/playground/docs`

Do not move old plans in bulk without preserving links from existing conversations.

## Active vs Archived Plans

Active plans should use current paths from `/Users/fujie/code/workspace.toml`; prose documents must not redefine `[workspace]` or `[rules]` values.

Historical plans with old paths should be moved to `/Users/fujie/code/docs/archive` instead of being edited in place.
