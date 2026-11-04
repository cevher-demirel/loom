# Stage 23g - design tokens and button hierarchy

Tokens live in `:root` (additive): spacing `--space-1..8`, radii `--radius-xs..pill`,
type `--fs-xs..xl` (12px floor), motion `--motion-fast/base/slow`, stacking `--z-*`,
focus `--focus-ring`/`--focus-offset`, status `--danger*`. Existing surface/text/accent
tokens (`--bg --surface --surface-raised --border --text --text-muted --accent*`) and the
glow tokens (`--glow-*`, `--btn-violet`) are unchanged.

Mechanical consolidations (values identical, so no visual change; verified by pixel diff
on the main screens): focus outline, z-index numbers, danger colours, common radii.

Buttons: primary / secondary / tertiary (`.link-btn`) / destructive (`.danger-btn`) /
disabled / loading (`.is-loading`). Glow is reserved for the recording journey.
