# Checked action sequences

The sequence runner validates a JSON plan, loads its reference images, and executes a bounded series of inputs with local visual comparisons. Create plans from the current screen and objective. References must match the native game-client dimensions and UI layout.

## Start with your own reference

From the skill's `runtime` directory:

```powershell
$mcPython = (Resolve-Path '.\.venv\Scripts\python.exe').Path
& $mcPython .\minecraft_control.py capture --focus --capture captures\reference.png --max-width 7680
```

Inspect that image. Select a stable region that tests a meaningful assumption, such as an unobscured menu border. Avoid dynamic scenery, counters, tooltips, or item stacks unless their change is what the check should detect. The full reference image is loaded; `regions` selects what is compared.

The example below is an **observation-only template**: its step sends no keys, buttons, or mouse motion. The dimensions and rectangle are illustrative; replace them with values from your image. Save the adapted JSON as `plans/observe.json`, creating the `plans` folder if needed. Its image path is relative to the plan file.

```json
{
  "version": 1,
  "name": "Observe a stable region",
  "client_size": [1280, 720],
  "max_seconds": 3,
  "checks": {
    "stable": {
      "image": "../captures/reference.png",
      "regions": [[400, 180, 430, 190]],
      "mode": "pixels",
      "max_mean_error": 3
    }
  },
  "start_check": "stable",
  "steps": [
    {
      "seconds": 0.08,
      "settle": 0.12,
      "expect_before": "stable",
      "expect_after": "stable"
    }
  ]
}
```

Validate files and schema without game input:

```powershell
& $mcPython .\minecraft_sequence.py .\plans\observe.json --dry-run
```

After inspecting the current game and confirming the plan's assumptions, execute it:

```powershell
& $mcPython .\minecraft_sequence.py .\plans\observe.json --focus --capture captures\observed.png --report reports\observed.json
```

`--dry-run` does not inspect the live game, judge feasibility, or validate that a crop is meaningful. The observation-only plan demonstrates the file format; the agent adds suitable actions and state checks for the actual task.

## Plan fields

| Field | Meaning |
| --- | --- |
| `version` | Must be `1`. |
| `name` | Optional label. |
| `client_size` | Native `[width, height]`; integers from 1 to 7680. Every reference must have this exact size. |
| `max_seconds` | Execution budget from 1 to 30 seconds; defaults to 20. Leave room for checks and settling. |
| `checks` | Named visual checks. Each needs an image, regions, and optional mode/threshold. |
| `start_check` | A loaded check that must pass before any input. |
| `steps` | One to 32 expanded steps. Unknown fields are rejected. |

Each check accepts 1–16 regions. Rectangles are `[left, top, right, bottom]`, with exclusive right/bottom edges, contained within the native image. `max_mean_error` is between 0 and 30 and defaults to 8. All regions must meet that maximum mean pixel error.

Modes:

- `pixels`: RGB differences.
- `bright_text`: masks bright, near-neutral pixels before comparison; useful for text changes, but it does not read characters or coordinates.
- `red_pixels`: masks red-dominant pixels; it can track a carefully selected HUD region, but other red pixels can interfere.

## Step fields

| Field | Meaning |
| --- | --- |
| `label` | Optional label, at most 160 characters. |
| `keys`, `buttons` | Arrays of supported input names; empty by default. |
| `seconds` | Hold duration, 0.02–5 seconds; defaults to 0.08. |
| `settle` | Released settling time, 0.02–2 seconds; defaults to 0.12. |
| `dx`, `dy` | Integer relative mouse totals between -2000 and 2000; default 0. |
| `at` | Native menu point `[x, y]`; requires `expect_before` and cannot combine with relative motion. |
| `expect_before` | Named check required before this input. |
| `expect_after` | Named check after settling; required on the final step. |
| `watch` | Up to eight named checks sampled during the hold. |
| `repeat` | One to 16 repetitions, expanded within the 32-step limit. Requires fixed aim, no menu point, and a `progress` check when greater than one. |
| `progress` | Compares before/after regions for a minimum amount of change; requires `regions` and `min_mean_error`, with optional `mode`. |

`progress.min_mean_error` is between 0.01 and 255. A progress check passes if at least one selected region changes by that amount. Pick a region that distinguishes useful movement or resource change from animation. Passing progress alone does not prove the desired effect.

Watches sample approximately every 0.25 seconds plus image-processing time. After-check retries wait briefly for visual settling; they do not replay input. Each step releases its inputs before settling. Repeated holds therefore contain release gaps.

## Build useful checks

Use distinct references for distinct menu types and transitions. A common panel border may look identical in multiple menus. Require the appropriate menu before a coordinate action, and verify the actual output through inventory inspection.

A movement batch can watch a stable HUD region and compare progress between short chunks, but the agent still needs to inspect the route and stopping point. Tool breakage, terrain hazards, and newly exposed material may require ending the batch and observing again.

Do not increase error thresholds merely to pass a mismatch. Inspect whether the view, selected item, dimensions, cursor, or tooltip changed. Rebuild reference crops when the GUI scale or layout changes.

## Failure and recovery

The runner writes a report and attempts a final capture while focus and stop conditions permit it. A stopped step may already have sent some or all of its input. Read `status`, `completed_steps`, `stopped_at`, and each step's `input_completed` together with a fresh screenshot.

Continue from current game and cursor state. Replaying a failed craft or resource-consuming prefix can duplicate actions or spend different ingredients. A report marked `complete` means the configured input/check sequence completed; inspect the game to establish the user's outcome.
