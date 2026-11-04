# F. Loom Map deep dive

Evidence: `screenshots/07_loom_map/` (network at 3/30/120 dreams, empty, selected node, filters, timeline, list, element detail), `annotated/A1`, `A8`; code read of the graph renderer. Seeded data only.

## The ten questions
1. **What does a first-time user understand when the map opens?** A pleasant star: "You" in the centre, coloured nodes on spokes. Subtitle "Explore patterns across dreams" and the legend ("You / Tap to open / Closer = more frequent") explain frequency, not connection. They learn that things recur, not how things relate.
2. **Can users distinguish symbols, emotions, people, places?** Partly: each category has a colour and an icon (heart = emotion, person, house, wind...), and the Filters sheet names the four types. Colours are muted and labels 11.7px, so at a glance they are distinguishable only by someone who already knows the scheme. There is no legend of the four types on the map itself.
3. **Are connections meaningful or confusing?** The lines are not connections between elements; they are "You -> element" spokes with small dots (dots along a spoke roughly encode frequency). Meaningful pairings exist in the data (the node sheet lists "Connected to: a city at night 4, Flying 3...") but are not drawn.
4. **Can a user understand why two nodes are connected?** No, not from the Network view. The node sheet lists co-occurring elements with counts, but as non-interactive text; the connection sheet (`openLoomConnectionPreview`) exists in code and has no caller.
5. **Natural path from a node to related dreams?** Yes and good: tap node -> sheet -> "View related dreams ->" -> element detail with Overview/Dreams/Personal Meaning tabs. This is the strongest part of the flow.
6. **Useful with 3 dreams?** Not yet. 11 nodes appear, every one with frequency 1, so distance carries no meaning and nothing explains that repetition is what makes the map useful.
7. **Useful with 30 dreams?** Moderately. 12 nodes (cap), clear spokes, readable at 390 but labels are small; 15 of 27 elements are not on the Network.
8. **100+ dreams?** Same 12 nodes (checked at 120 seeded dreams); the cap hides most of the data with no notice (L-02). Performance was fine at 120. List view still shows 27 elements, so it is the practical view for scale.
9. **Are filters understandable?** Yes: plain labels, Reset/Apply, time range. Weakness: the funnel icon (36px) has no text and the active-filter state is not visible on the map after applying (not verified beyond the sheet; recorded as an observation).
10. **Does it offer a genuine discovery experience?** The Home "Your recent discovery" card ("disgusted and a city at night - Together in 4 dreams") is a real discovery, but its target ("Review in Loom Map") lands on a map that cannot show that pairing. The discovery and the map are disconnected.

## Three highest-impact improvements (no more)
**1. Make a selected node reveal its connections (L-01).** Keep the calm star at rest. When a node is selected, draw faint lines from it to the nodes it co-occurs with (existing `computeDiscoveries` data), and make the "Connected to" items buttons that open the existing connection sheet. Benefit: the user finally sees *why* things are linked and the Home discovery card lands on something visible. Effort M; risk medium.

**2. Be honest about what is shown (L-02 + L-03).** Fill the existing, never-populated note: "Showing the 12 most frequent of 27 - see List for all". Under ~5 dreams, replace the legend line with "Elements gather here as they repeat across your dreams". Benefit: trust and no false expectation. Effort S; risk low.

**3. Make it hit-able and readable on a phone (L-04 + L-05).** Raise toggle/zoom targets to 44px, labels to >=12px, and let the graph use the empty ~20% of height on tall phones. Benefit: touch accuracy and legibility without changing the visual identity. Effort S-M; risk low-medium.

Deliberately not proposed: more node types, animation, extra modes, onboarding.
