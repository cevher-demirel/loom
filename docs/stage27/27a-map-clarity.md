# Stage 27a -- Map clarity and a single load-error message

Source: Stage 26 audit findings F-01, F-07, F-08, F-10 (baseline main c30b869). Frontend only.

## Label approach (F-01)
Considered: (A) show labels only for the selected node and its neighbours; (B) bigger labels everywhere; (C) a readable minimum size, with a label shown only when it clears every other node and label.
A was rejected as the main rule: at rest nothing is selected, so the Map would be unlabeled icons, and several elements share an icon (every emotion is a heart). B alone overlaps.
Chosen: C. Labels are sized so they are at least 11px on screen (the graph is scaled down to fit a phone, which used to shrink 12px labels to 5-9px). Priority when space is short: selected node, its neighbours (A's idea, kept as the tie-breaker), then most frequent. A hidden name stays in its node's accessible name, a note says how many are hidden, and zooming in or tapping the node shows it.
Graph layout, node set, ranking, colours and relationships are unchanged.

## Other changes
- F-07: the empty Map hides zoom buttons and the legend; the message and Record button remain, and so does Filter.
- F-08: a one-line description under the Network/Timeline/List switch changes with the view. The Timeline's duplicate hint line was removed.
- F-10: after a failed load the Journal shows one card with Retry inside it; the global banner stays on other tabs; the generic "server may be waking" toast no longer stacks on top.

## Tests
`tests/browser/test_stage27a_map_clarity.py` (new). Stage 25 tests were updated for the new location of Retry (inside the card).
