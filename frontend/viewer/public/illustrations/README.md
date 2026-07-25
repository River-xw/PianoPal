# Home mode illustrations

Each home card uses two illustrations with the same canvas size:

- `learn-idle.svg` / `learn-active.svg`
- `perform-idle.svg` / `perform-active.svg`
- `profile-idle.svg` / `profile-active.svg`

The `-active` frame fades in on mouse hover and keyboard focus. Keep both frames aligned to the same `viewBox` (these placeholders use `0 0 200 140`) so the transition does not jump.

SVG is preferred for vector artwork. For raster artwork, transparent WebP at 2× size is the best default; update the paths in `src/components/HomePage.jsx` if you change the extension.
