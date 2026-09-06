# Minecraft Gameplay

A Windows keyboard, mouse, and screenshot toolkit for Codex and other computer-use agents. The agent observes the game, chooses actions, and verifies the result; the Python runtime supplies bounded controls and optional visual checks.

Use it to move, look around, gather materials, craft, explore, and build through the visible game interface. The runtime uses Windows input events and screenshots. It does not include an agent model, game client, world save, or game-memory interface.

## Quick start with Codex

1. Download and extract the ZIP, or clone this repository. Keep the entire folder, including the visible `agents` and `scripts` directories.
2. Open the extracted `minecraft-gameplay` folder as a **local Codex project on the Windows PC running Minecraft**. The project root is the directory containing this README and `AGENTS.md`.
3. Launch Minecraft, enter a world, and keep the game window visible. Give Codex this task, changing the gameplay goal as desired:

> Read AGENTS.md, README.md, and agents/skills/minecraft-gameplay/SKILL.md. Run scripts/setup_repository.py, set up the Windows Python environment, and install the runtime requirements if needed, then run the mock tests. Use the controller to find my Minecraft window and inspect a fresh screenshot. Once you can see the game, gather wood and craft basic tools using screenshots and normal keyboard/mouse controls. Verify the result in my inventory.

Codex reads the root [AGENTS.md](AGENTS.md) and follows its link to the visible [gameplay skill](agents/skills/minecraft-gameplay/SKILL.md). It can perform the setup commands below when its local tools and permissions allow it. No global skill installation is needed. [Official project-instruction documentation](https://learn.chatgpt.com/docs/agent-configuration/agents-md).

The setup script also creates a small local registration under `.agents/skills` so Codex can discover the skill in its skill picker. It points to the visible source instead of copying the controller. If the newly registered skill does not appear, restart Codex. These generated files are local and are excluded from releases. [Official skill documentation](https://learn.chatgpt.com/docs/build-skills).

The folder supplies the gameplay instructions and controller. The agent still needs local command execution, image inspection, and access to the game's desktop. Attaching the ZIP to a cloud chat alone does not connect that chat to Minecraft.

## Requirements

- Windows with Minecraft running on an interactive desktop. Java Edition is the primary target; other editions and custom launchers may need window-detection changes.
- Windows Python 3.8 or newer and Pillow, installed below.
- An agent environment that can run local Windows commands, read the resulting images, and access the desktop containing the game.

A cloud task or browser-only tool cannot operate this local adapter. A Linux Python process cannot load its Win32 backend. Codex can run natively on Windows; its permissions and desktop isolation still apply. If the shell cannot see the game, use an approved local execution environment with access to that desktop. [Official Windows sandbox documentation](https://learn.chatgpt.com/docs/windows/windows-sandbox).

## Manual setup

Codex can run these commands for you, or you can open PowerShell at the repository root and run them yourself:

```powershell
py -3 scripts\setup_repository.py
Set-Location agents\skills\minecraft-gameplay\runtime
py -3 -m venv .venv
$mcPython = (Resolve-Path '.\.venv\Scripts\python.exe').Path
& $mcPython -m pip install -r requirements.txt
& $mcPython -m unittest -q
```

The setup script uses only Python's standard library. It creates local skill registration and `.gitignore` rules from `gitignore.template`, preserves existing ignore rules, and can be rerun. It does not install dependencies or change Codex's global settings. An existing skill registration that it did not create is left unchanged and reported as a conflict.

The tests use fake inputs and synthetic images; they send no game input. A compatible existing Windows Python with Pillow can be used instead of the virtual environment.

## Optional installation across projects

For personal installation across projects, copy the entire `minecraft-gameplay` skill folder from `agents/skills` into your user `.agents/skills` directory. Keep its `runtime` and `references` folders together, and create the Python environment in the installed runtime location. Copy the complete visible skill rather than the generated local registration, which points back to this repository.

The skill helps the agent choose and check actions. It does not grant tool permissions or turn a remote environment into a local desktop session.

## First observation

From the runtime directory, with `$mcPython` set as above:

```powershell
& $mcPython .\minecraft_control.py status
& $mcPython .\minecraft_control.py capture --focus --capture captures\current.png --max-width 7680
```

Inspect the returned screenshot before taking an action. Check whether a menu is open, where the player stands, what is selected, and which nearby surfaces can be reached. If several game windows are listed, pass a current `--hwnd NUMBER` to select one.

After observing a clear path, a short forward action could be:

```powershell
& $mcPython .\minecraft_control.py act --focus --keys w --seconds 0.2 --capture captures\after-step.png
```

Inspect `after-step.png` before extending the movement. Input duration and mouse deltas require calibration for the current settings.

## Controls and checked sequences

- [Command reference](agents/skills/minecraft-gameplay/references/commands.md): movement, camera control, mining, menu clicks, captures, and stopping.
- [Sequence guide](agents/skills/minecraft-gameplay/references/sequences.md): create plans using your own current screenshots, choose comparison regions, and validate before execution.
- [Agent skill](agents/skills/minecraft-gameplay/SKILL.md): observation, planning, batching, and recovery workflow.

Individual holds are limited to 5 seconds. Sequences allow at most 32 expanded steps and a 30-second budget. Visual checks compare selected pixels; a passing report does not establish that an item was crafted or a destination reached.

## Stop

Hold **F8** or switch focus away from Minecraft to interrupt an action. A persistent stop can also be requested from the runtime directory:

```powershell
& $mcPython .\minecraft_control.py stop
```

After inspecting why execution stopped, clear the stop file when ready to continue:

```powershell
& $mcPython .\minecraft_control.py reset-stop
```

Use one live controller. Inputs are released when an action ends, and a watchdog supplies backup cleanup. Keep Minecraft visible and restore minimized windows before use.

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| `py` is not recognized | Install Windows Python 3.8 or newer, or use the full path to a compatible existing Windows Python executable. |
| Pillow cannot be imported | Install `requirements.txt` with the same interpreter used to run the controller. |
| Codex cannot find the gameplay instructions | Open the directory containing `AGENTS.md` and `agents` as the project root. Ask Codex to read `agents/skills/minecraft-gameplay/SKILL.md`. For skill-picker discovery, run setup and restart Codex if needed. |
| No Minecraft window is listed | Enter a world in Java Edition and restore its window. Check that the command is running on the same Windows desktop. Custom launchers may require adapting the title/process checks. |
| Access, focus, or screenshot errors | Check the reported error, window visibility, Windows permissions, and desktop isolation. The adapter must run in an approved local environment with access to the game. |
| Movement or aiming differs from expectations | Check key bindings, sensitivity, and window size; calibrate short actions using fresh screenshots. |

## Repository contents and publishing

Publish the **contents of the `minecraft-gameplay` folder** as your GitHub repository root, so this README appears on the repository's front page. All 15 source files have visible names and live at the root or inside `agents/` and `scripts/`. Drag those files and folders into GitHub's upload page, preserving their structure.

```text
README.md                  Setup and usage
AGENTS.md                  Instructions for agents working in this repository
LICENSE / NOTICE           Apache 2.0 license and author credit
gitignore.template         Rules installed locally by setup
agents/skills/minecraft-gameplay/
  SKILL.md                 Gameplay workflow for Codex
  references/              Controller commands and sequence guide
  runtime/                 Python controller, sequence runner, tests, requirements
scripts/package_gameplay.py Source ZIP builder
scripts/setup_repository.py Local Codex registration and Git ignore setup
```

The release ZIP also includes `MANIFEST.sha256.json` to verify its source files. Leave this generated manifest out of the GitHub source upload. You can attach the ZIP and its sibling checksum file to a GitHub release as downloads.

After local setup or gameplay, the working folder can also contain generated dotfiles, captures, environments, and reports. Use a fresh source copy or the package builder's explicit file list when uploading through a browser; `.gitignore` does not filter a browser's drag-and-drop selection.

## Development and packaging

Run the test command from Manual setup after changes to the runtime. The included 50 tests exercise controller and sequence behavior with fake inputs and synthetic images. They do not establish compatibility with every Minecraft version, launcher, desktop policy, or display configuration. Verify window detection and a fresh screenshot on each new machine before starting gameplay.

From the repository root, build a redistributable ZIP:

```powershell
py -3 scripts\package_gameplay.py
```

The builder uses an explicit list of source files. It excludes generated local registration and ignore files, captures, user plans, environments, caches, and Git history. The ZIP includes `MANIFEST.sha256.json` and has a sibling SHA-256 file. Review the allowlist when adding public files.

Captures, action output, and sequence reports created during use can contain player names, screen contents, and local file paths. Run the setup script to install Git ignore rules before gameplay or development. The package builder excludes these generated files whether setup has run or not.

## License

Copyright 2026 Wuyang Zhou and Tianyu Wei. Licensed under [Apache License 2.0](LICENSE). Pillow is installed separately and retains its own license. Minecraft and Codex are separate products; this toolkit is not affiliated with Mojang, Microsoft, or OpenAI.
