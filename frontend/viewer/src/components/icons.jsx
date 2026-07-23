// Minimal stroke-based icon set (no icon library dependency, matches the
// project's zero-extra-deps style) -- 24x24 viewBox, currentColor stroke,
// sized/colored by the caller via className/style.
const BASE_PROPS = {
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.6,
  strokeLinecap: "round",
  strokeLinejoin: "round",
};

export function IconLightbulb(props) {
  return (
    <svg {...BASE_PROPS} {...props}>
      <path d="M9 18h6M10 21h4M12 3a6 6 0 0 0-3.6 10.8c.6.45 1.1 1.2 1.1 2.2h5c0-1 .5-1.75 1.1-2.2A6 6 0 0 0 12 3Z" />
    </svg>
  );
}

export function IconTarget(props) {
  return (
    <svg {...BASE_PROPS} {...props}>
      <circle cx="12" cy="12" r="8" />
      <circle cx="12" cy="12" r="4" />
      <circle cx="12" cy="12" r="0.6" fill="currentColor" />
    </svg>
  );
}

export function IconRepeat(props) {
  return (
    <svg {...BASE_PROPS} {...props}>
      <path d="M4 7h13a3 3 0 0 1 3 3v1M20 17H7a3 3 0 0 1-3-3v-1" />
      <path d="M7 4 4 7l3 3M17 20l3-3-3-3" />
    </svg>
  );
}

export function IconChevronDown(props) {
  return (
    <svg {...BASE_PROPS} strokeWidth={1.8} {...props}>
      <path d="m6 9 6 6 6-6" />
    </svg>
  );
}
