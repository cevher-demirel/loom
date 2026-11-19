# B. Findings register

No P0 findings: no core journey was found to lose data or be fully blocked in portrait; the Stage 21 submission mechanism was not touched. 'D' = data-integrity question for the owner (nothing was changed).

Priorities: P0 blocks a core journey or risks data loss; P1 significant usability/accessibility issue; P2 noticeable inconsistency or friction; P3 optional polish.

### L-01 [P1] Loom Map / Network
- **Element:** Graph (#loom-graph-wrap), legend
- **Observed:** Only 'You -> element' spokes are drawn. Element-to-element connection lines were removed ('Option 2' comment in index.html); the node sheet's 'Connected to' items are plain spans, and openLoomConnectionPreview() has no caller, so the connection sheet is unreachable. There is no Discoveries list under the Network view although a code comment says there is.
- **Viewport / interaction:** All viewports; any seeded size (3/30/120 dreams)
- **Why it matters:** The product's signature promise is 'discover connections', but the Network view shows frequency only. A first-time user cannot see why two things relate.
- **Recommendation:** On node tap, draw faint lines from the selected node to its co-occurring nodes and make the 'Connected to' items buttons that open the existing connection sheet. Keep the calm star as the resting state.
- **Complexity:** M  |  **Regression risk:** Medium: touches graph render + one handler; existing node/tap tests need extending

### L-02 [P1] Loom Map / Network
- **Element:** Node cap (GRAPH_MAX_NODES=12, 4 per category); #loom-graph-dropped-note
- **Observed:** Network shows at most 12 nodes. With 30 and 120 seeded dreams it still shows 12 of 27 elements. The 'dropped note' paragraph exists in HTML but no script ever fills it, so omission is silent.
- **Viewport / interaction:** 390x844, 30 and 120 dreams
- **Why it matters:** People will assume the map is complete. Trust in the data is part of the product direction.
- **Recommendation:** Fill the existing note: 'Showing the 12 most frequent of 27. See all in List.' Link it to List view.
- **Complexity:** S  |  **Regression risk:** Low

### N-02 [P1] Global / Home
- **Element:** #home-discovery-review-btn, #insights-legend-toggle
- **Observed:** Two links are <24px tall (18px and 19px), failing WCAG 2.2 AA target size (2.5.8). Header gear, back buttons (32px), search icon (32px), Home footer links (24px) pass the 24px minimum but miss the 44px guideline.
- **Viewport / interaction:** 390x844 / touch
- **Why it matters:** Hard to tap accurately; accessibility minimum.
- **Recommendation:** Add padding / min-height 44px hit-area.
- **Complexity:** S  |  **Regression risk:** Low

### R-01 [P1] Emotion Wheel explorer
- **Element:** Whole layout (#feel-scroll, dock, bottom nav)
- **Observed:** In landscape 844x390 the header, group row, tray, dock and bottom nav leave one row of space; the wheel is not visible.
- **Viewport / interaction:** 844x390 landscape
- **Why it matters:** Core journey becomes unusable when the phone is rotated; Stage 20 only budgeted portrait down to 390x600.
- **Recommendation:** In landscape/short height (<=420px) hide the bottom nav on the explorer and place the wheel and groups side by side.
- **Complexity:** M  |  **Regression risk:** Medium

### R-02 [P1] Record a dream
- **Element:** #interpret-btn (Continue), date/voice rows
- **Observed:** With a keyboard-height viewport (390x420, emulated) only the text box fits; Continue is below the fold so the user must scroll with the keyboard open.
- **Viewport / interaction:** 390x420 emulated keyboard
- **Why it matters:** Primary action unreachable while typing; a real OS keyboard could not be tested.
- **Recommendation:** Make Continue sticky above the keyboard using visualViewport; collapse date/voice rows while the text box has focus.
- **Complexity:** M  |  **Regression risk:** Medium

### A-01 [P2] Auth
- **Element:** Login/Sign Up
- **Observed:** Forgot-password link and the show-password eye are small; landing opens on 'Sign Up' for first-time and shows brain/tagline illustration that pushes the form below the fold at 320x568.
- **Viewport / interaction:** 320x568
- **Why it matters:** Returning users are the common case and need Log In first.
- **Recommendation:** Remember last-used tab; shrink illustration at <=600px height.
- **Complexity:** S  |  **Regression risk:** Low

### D-01 [P2] Dream Detail
- **Element:** Back link
- **Observed:** Back label says 'Archive' when opened from Journal, 'Journal' after a new submit; tab and title say 'Journal'.
- **Viewport / interaction:** 390x844
- **Why it matters:** Inconsistent vocabulary for the same place.
- **Recommendation:** Use 'Journal' everywhere.
- **Complexity:** S  |  **Regression risk:** Low

### I-01 [P2] Insights / Landscape
- **Element:** Flower, legend, caption
- **Observed:** Three dreams yield a headline '67% 2 of 3'; small samples are not flagged. Percent uses only dreams with a reading as denominator (verified in computeEmotionFrequency).
- **Viewport / interaction:** 390x844, 3 dreams
- **Why it matters:** Percentages from tiny samples look more certain than they are.
- **Recommendation:** Add 'Early reading, based on 3 dreams' under the flower when dreams-with-reading < 5. No calculation change.
- **Complexity:** S  |  **Regression risk:** Low

### I-02 [P2] Insights / Landscape
- **Element:** Colors
- **Observed:** Wheel colors (fear #3d9be0, sad #7266b5, trust #4e7a46, disgust #c02cbc) differ from Landscape colors (fear #8b7cf0, sadness #4d72c4, trust #5fd9a8, disgust #a85fd0). Wheel says 'Happy', Landscape says 'Joy'.
- **Viewport / interaction:** All
- **Why it matters:** The same family changes colour between screens, breaking the learned mapping.
- **Recommendation:** Pick one palette source and derive both; label 'Happy' consistently.
- **Complexity:** M  |  **Regression risk:** Medium (colour constants, charts)

### J-01 [P2] Journal
- **Element:** #journal-record-btn, #journal-head-add-btn
- **Observed:** Three routes to 'new dream' on one screen (header +, New Dream button, Home/Record). The header + is a 32px target.
- **Viewport / interaction:** 390x844
- **Why it matters:** Redundant primary actions dilute hierarchy.
- **Recommendation:** Keep the button; remove the header + or make it the only one.
- **Complexity:** S  |  **Regression risk:** Low

### J-02 [P2] Journal
- **Element:** #archive-search-input
- **Observed:** Placeholder is clipped ('...symbols, peop') at 390 and narrower.
- **Viewport / interaction:** 320-390
- **Why it matters:** Truncated hint looks unfinished.
- **Recommendation:** Shorten: 'Search dreams, symbols, people'.
- **Complexity:** S  |  **Regression risk:** Low

### J-03 [P2] Journal
- **Element:** Colored square on each card
- **Observed:** A coloured square at the left of each card has no label or legend (appears to be the dominant emotion colour).
- **Viewport / interaction:** All
- **Why it matters:** Meaning is undiscoverable and not exposed to assistive tech.
- **Recommendation:** Add an aria-label and show the emotion name in the tag row (already there) or replace by the emotion icon.
- **Complexity:** S  |  **Regression risk:** Low

### L-03 [P2] Loom Map / Network
- **Element:** Legend 'Closer = more frequent'
- **Observed:** With 3 dreams, 11 nodes appear and every one has frequency 1, so distance carries no information. Nothing says the map gets richer with more dreams.
- **Viewport / interaction:** 390x844, 3 dreams
- **Why it matters:** Early users see a decorative star and may judge the feature as shallow.
- **Recommendation:** Below ~5 dreams show a one-line honest caption ('Elements appear here as they repeat across dreams') and de-emphasise spokes.
- **Complexity:** S  |  **Regression risk:** Low

### L-04 [P2] Loom Map / Network
- **Element:** Node labels, view toggle, zoom buttons
- **Observed:** Node labels measure 11.7px (10.6px at 320 wide); Network/Timeline/List toggle buttons are 28px tall; zoom buttons 34px; at 320 wide symbol nodes are 32x28px.
- **Viewport / interaction:** 320, 375, 390 / touch
- **Why it matters:** Small targets and small labels are hard to read and hit on a phone.
- **Recommendation:** Raise toggle and zoom targets to >=44px (padding or hit-area), label min 12px.
- **Complexity:** S  |  **Regression risk:** Low-Medium (graph layout assumptions)

### L-05 [P2] Loom Map / Network
- **Element:** Space under legend
- **Observed:** About 20% of the 390x844 viewport below the legend is empty while labels stay tiny.
- **Viewport / interaction:** 390x844, 430x932
- **Why it matters:** Unused space could carry larger labels or a one-line reading of the selected node.
- **Recommendation:** Let the graph wrap grow into available height (existing measure-and-cap logic already handles short screens).
- **Complexity:** M  |  **Regression risk:** Medium

### L-06 [P2] Loom Map / Timeline
- **Element:** Two stacked 'Timeline' controls; dream excerpts
- **Observed:** Network/Timeline/List toggle sits above a second Timeline/Month/Patterns toggle. Excerpts are cut mid-word without ellipsis ('felt disgusted the whole t').
- **Viewport / interaction:** 390x844
- **Why it matters:** Two levels of the same word confuses orientation; mid-word cuts look like a bug.
- **Recommendation:** Rename inner tabs (Chronology/Month/Patterns) or lead with the element name; apply text-overflow ellipsis/word boundary clamp.
- **Complexity:** S  |  **Regression risk:** Low

### N-01 [P2] Global navigation
- **Element:** Bottom nav labels
- **Observed:** Labels are 10.88px at 4.41:1 contrast against the bar (just under 4.5:1 AA).
- **Viewport / interaction:** All mobile
- **Why it matters:** Small, slightly low-contrast text.
- **Recommendation:** Use 12px and a lighter muted token (#a9a1d4).
- **Complexity:** S  |  **Regression risk:** Low

### R-03 [P2] Emotion tray
- **Element:** Expanded tray at 320x568
- **Observed:** Tray title wraps to two lines, rows truncate ('Trust -> Grateful -> Blessed' wraps), about two choice rows remain; family title can slide under the header.
- **Viewport / interaction:** 320x568
- **Why it matters:** Cramped at the smallest supported width.
- **Recommendation:** Shorter title ('Selected (3)') and single-line path with ellipsis at <=340px.
- **Complexity:** S  |  **Regression risk:** Low

### S-01 [P2] Settings
- **Element:** Profile vs Account pages
- **Observed:** 'Profile' page holds only avatar, name and Log out. The profile fields ('About You') live on the 'Account' page together with email, export and delete.
- **Viewport / interaction:** 390x844
- **Why it matters:** Names do not match contents; users look for their profile details under Profile.
- **Recommendation:** Move About You into Profile, keep email/data/delete under Account.
- **Complexity:** M  |  **Regression risk:** Medium (markup move)

### S-02 [P2] Settings / Account
- **Element:** Delete flow
- **Observed:** Delete confirm is inline red text with a text-weight button, not a dialog; the destructive action is low emphasis and shares visual weight with Save.
- **Viewport / interaction:** 390x844
- **Why it matters:** Irreversible action needs clear, deliberate presentation.
- **Recommendation:** Use the standard danger button inside a bordered section with a short consequence line.
- **Complexity:** S  |  **Regression risk:** Low

### X-01 [P2] Cold start
- **Element:** Splash (#app-splash)
- **Observed:** A fixed 1.7s hold + 0.5s fade runs on every cold open, regardless of whether the app is ready.
- **Viewport / interaction:** All
- **Why it matters:** 2.2s of non-skippable delay each launch (about 0.7s with reduced motion).
- **Recommendation:** Hide as soon as first data is ready, with a 600ms minimum.
- **Complexity:** S  |  **Regression risk:** Low

### X-02 [P2] Design system
- **Element:** Primary buttons
- **Observed:** Two primary-button looks: glowing violet gradient (Home 'Record a Dream', 'Add to Dream', Try again) vs flat lavender (Journal 'New Dream', 'View related dreams', 'Create Account').
- **Viewport / interaction:** All
- **Why it matters:** Primary action weight changes across screens without a rule.
- **Recommendation:** Define: glow gradient = recording journey only; flat = everything else (document the rule).
- **Complexity:** S  |  **Regression risk:** Low

### J-04 [P3] Journal
- **Element:** Filter chips
- **Observed:** Chips are 32px tall and scroll horizontally; 'Symbols' is cut off at 390.
- **Viewport / interaction:** 390
- **Why it matters:** Mild; cut-off chip does hint at scroll.
- **Recommendation:** Add 12px side padding fade or wrap.
- **Complexity:** S  |  **Regression risk:** Low

### L-07 [P3] Loom Map / Element detail
- **Element:** Failure copy 'The connection dropped partway through' + 'Try again'
- **Observed:** In the mock the AI stream is unavailable so the error state rendered: 'Try again' is an ~18px text button. (Induced by the test backend, not a production observation.)
- **Viewport / interaction:** 390x844
- **Why it matters:** Error recovery targets should be as large as the main CTA.
- **Recommendation:** Use the standard secondary button for retry.
- **Complexity:** S  |  **Regression risk:** Low

### I-03 [D] Insights / Landscape
- **Element:** computeEmotionFrequency()
- **Observed:** Data-integrity question (not changed): tags come from AI 'emotions_plutchik' when present, otherwise from 'emotions_reported'. Since Stage 19, users pick emotions explicitly; those picks are ignored for the Landscape whenever the AI tags exist, and specific labels like 'Worried' are not plottable at all.
- **Viewport / interaction:** All
- **Why it matters:** The flower may not reflect what the person chose.
- **Recommendation:** Owner decision: keep AI-reading basis but say so in the caption, or blend. Do not change silently.
- **Complexity:** -  |  **Regression risk:** -
