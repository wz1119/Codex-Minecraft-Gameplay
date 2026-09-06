---
name: minecraft-gameplay
description: Play Minecraft on a local Windows desktop using screenshot observation, bounded keyboard and mouse input, and checked action sequences. Use for in-game movement, gathering, crafting, exploration, and building.
license: Apache-2.0
---

# Minecraft gameplay

Use the Python adapter in `runtime/` beside this file. It requires Windows Python with Pillow and access to the interactive desktop containing Minecraft. A configured interpreter or `runtime/.venv/Scripts/python.exe` can run it. Resolve paths relative to this skill, not the shell's initial directory.

Read [commands](references/commands.md) for CLI options. Read [sequences](references/sequences.md) when constructing a checked batch. Work within the current task and tool permissions.

## First-use setup

Reuse a suitable Windows Python environment if available. Otherwise, from this skill's `runtime` directory, run:

```powershell
py -3 -m venv .venv
$mcPython = (Resolve-Path '.\.venv\Scripts\python.exe').Path
& $mcPython -m pip install -r requirements.txt
& $mcPython -m unittest -q
```

Use that interpreter for controller and sequence commands. These tests use fake inputs and synthetic images. Set up and test once per environment; do not repeat installation on every gameplay action. If local Windows execution, image inspection, or desktop access is unavailable, explain the specific missing capability.

## Observe the current game

Run `minecraft_control.py status`, then capture and inspect the selected game's client area. Use `--hwnd` from the fresh status result if multiple game windows are open. Classify gameplay versus menus, and establish dimensions, footing, selected item, resources, and reachable targets.

Use native-size screenshots for sequence references (`capture --max-width 7680`). For resized screenshots, convert menu points back to the returned `source_size`. Camera control uses relative `dx`/`dy`; `at` is for visibly open menus.

If the adapter cannot see the game, check the Windows execution environment and desktop access. Do not interpret an enumeration error as an empty or closed game. Observe the environment's permission outcome.

## Plan and act

Choose a milestone from the user's goal and observed resources. Budget tools, materials, lighting, and return access before committing to a longer route. Establish a useful short action at the current sensitivity and material, then extend only across inspected terrain or a verified menu layout.

Separate camera alignment from sustained mining; relative deltas are spread through the hold. Verify clearance before advancing. Use an appropriate tool for visible material and inspect for changes in footing, tool state, or surrounding blocks.

Before crafting, inspect ingredients, recipe layout, quantities, cursor contents, and destination slots. Afterward, verify the output in inventory. A stable panel outline confirms menu layout, not item identity or crafting success. Keep the cursor off comparison regions when a tooltip would obscure them.

For bounded sequences, use `expect_before` at menu transitions and coordinate actions, `watch` for stable conditions during holds, and `progress` when repeating an action. Choose checks from the current HUD and layout. Pixel changes are stall signals, not a semantic count of movement or collected items.

Do not repeat menu coordinates or camera deltas with `repeat`; that mechanism requires fixed aim and a progress check for every repetition. Respect the runner's 32-step, 30-second, and 5-second-per-hold limits, leaving time for observations and settling.

## Inspect and recover

Inspect the final image and report after each batch. Distinguish completed input, passed comparisons, and the user's gameplay objective. Stop a roll when the terrain, inventory, or UI differs from its assumptions.

A stopped sequence can have partially moved the player, moved ingredients, or consumed items. Continue from a fresh observation; do not replay a resource-consuming prefix automatically. When movement stalls, inspect body alignment and reachable space before extending holds or mining more blocks.

Use one live input owner. F8, focus loss, and the persistent stop file interrupt input. Treat a user interruption as a stop; resume only when requested. Pause singleplayer through its visible menu when appropriate, and verify the requested outcome before reporting completion.
