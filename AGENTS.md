# Working in this repository

For a gameplay task, read [agents/skills/minecraft-gameplay/SKILL.md](agents/skills/minecraft-gameplay/SKILL.md). Resolve the current game state from fresh observations.

For first use, follow the Quick start and Manual setup in [README.md](README.md). Run `py -3 scripts/setup_repository.py` from the repository root with a suitable Windows Python interpreter, then set up the runtime requirements and run the mock tests within the task's permissions. Setup creates local Git ignore rules and registers the skill for Codex's skill picker; the visible `agents/` directory remains the canonical source. If registration is unavailable, these project instructions still route gameplay to the visible skill. Verify window detection and inspect a fresh screenshot before attempting gameplay. Report any missing local tool or desktop access clearly.

The runtime and its mock-only tests are in `agents/skills/minecraft-gameplay/runtime`. Run `python -m unittest -q` from that directory with Pillow installed after changing controller or sequence behavior. Test execution must remain independent of a running game.

Keep reusable workflow instructions and schema guidance in the visible skill and its references. Rerun setup after changing the skill metadata or `gitignore.template`. Keep user captures, custom plans, reports, generated `.agents/` registration, and local configuration outside the public source list. The package builder in `scripts/package_gameplay.py` is the authoritative release allowlist. Browser uploads must use that source list or a fresh source copy; Git ignore rules do not filter files dragged into a browser.
