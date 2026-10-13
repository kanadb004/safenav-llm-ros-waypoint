# Benchmark relabel (PLAN.md section 8A.2, D39)

Frozen rule, run once, unmodified by hand:

> For every spatial and multi_hop row, compute from the graph alone whether a unique target exists: enumerate plausible anchors (label-blind word/alias overlap with the command text, never the row's own expected label), apply the relation keyword(s) found in the command text, and apply the section 8.1 disambiguation policy (symmetric and inverse edge materialization, alias/tag overlap). Collect the set of distinct targets reached by any (anchor, relation) pair the text supports. Exactly one surviving target: structurally_answerable = true, expected unchanged. Zero or more than one surviving target: structurally_answerable = false, expected becomes "none". The rule sees only the graph and the command text, never a model prediction. It runs over all 130 rows unmodified by hand.

## Counts by category

| category | relabelled to none | total |
|---|---|---|
| multi_hop | 54 | 65 |
| spatial | 45 | 65 |

Total relabelled: 99 / 130.

## Ten worked examples

- `p0130` (spatial): "Can you go to the area that’s next to where we eat?"
  - original label: `meeting_room_a`
  - corrected label: `none`
  - reasoning: no candidate anchor/relation combination reached a target
- `p0131` (spatial): "Move to the room that’s directly beside the kitchenette."
  - original label: `meeting_room_a`
  - corrected label: `none`
  - reasoning: 2 distinct candidate targets: ['meeting_room_a', 'reception']
- `p0132` (spatial): "Take me to the space that’s next to the boardroom on the other side."
  - original label: `office`
  - corrected label: `none`
  - reasoning: 4 distinct candidate targets: ['kitchen', 'meeting_room_a', 'meeting_room_b', 'office']
- `p0133` (spatial): "Go to the workspace that’s right beside the second conference room."
  - original label: `office`
  - corrected label: `none`
  - reasoning: 4 distinct candidate targets: ['kitchen', 'meeting_room_a', 'meeting_room_b', 'office']
- `p0137` (spatial): "Go to the room that’s directly beside the docking bay."
  - original label: `lab`
  - corrected label: `none`
  - reasoning: 2 distinct candidate targets: ['charging_dock', 'lab']
- `p0138` (spatial): "Navigate to the area that’s next to the room where we keep the stock."
  - original label: `lab`
  - corrected label: `none`
  - reasoning: 2 distinct candidate targets: ['charging_dock', 'lab']
- `p0139` (spatial): "Take me to the workspace that’s beside the fabrication room."
  - original label: `lab`
  - corrected label: `none`
  - reasoning: 2 distinct candidate targets: ['lab', 'meeting_room_b']
- `p0141` (spatial): "Go to the area that’s right beside the room where we eat."
  - original label: `meeting_room_a`
  - corrected label: `none`
  - reasoning: no candidate anchor/relation combination reached a target
- `p0143` (spatial): "Navigate to the room that’s beside the boardroom a."
  - original label: `meeting_room_b`
  - corrected label: `none`
  - reasoning: 4 distinct candidate targets: ['kitchen', 'meeting_room_a', 'meeting_room_b', 'office']
- `p0144` (spatial): "Take me to the area that’s next to the conference room one."
  - original label: `meeting_room_b`
  - corrected label: `none`
  - reasoning: 4 distinct candidate targets: ['kitchen', 'meeting_room_a', 'meeting_room_b', 'office']

