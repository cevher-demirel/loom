# Stage 24b — why Brother + Barber shop (and Father + anything) were "not connected"

**Root cause.** `computeDiscoveries()` returned only the top `DISCOVERY_MAX_CARDS` (8) pairs of the whole archive,
ordered by shared-dream count then alphabetically. That list was also the data source for the Loom Map lines, node
preview "Connected to", connection preview, Focus mode, timeline and the Element "Recurs together" bullet. In an
archive with more than 8 stronger pairs, a genuine 2-dream relationship was dropped before any screen could see it
(the owner's Father node showed "No supported connections yet" although Father shares dreams with other elements).

**Fix.** `computeAllDiscoveries()` is the complete list (every pair sharing ≥ 2 dreams). Only the Home/Discoveries
*card list* keeps the 8-card cap. Map lines, previews, Focus mode and the Element bullet read the complete list.
Nothing is invented: a pair still requires the same two canonical elements tagged on ≥ 2 of the same dreams.

**Hidden nodes.** An element outside the 12-node network still appears in the node's "Connected to" list; the sheet
states that no line is drawn because it isn't on the map (a hidden node, not an unsupported relationship).

**What exact co-occurrence cannot do.** Two dreams that share Brother + Trust but where one is tagged *Barber chair*
and the other *Haircut* have no shared barber element, so no co-occurrence edge exists between those tags. That
similarity needs a text/semantic mechanism and is handled — labelled as such — in 24c.
