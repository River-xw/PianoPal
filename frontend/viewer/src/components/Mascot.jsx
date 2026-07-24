// A simple hand-drawn-style mascot (one rounded body/head shape, stick arms,
// a floating music note) -- purely decorative, used once on
// OnboardingPage/HomePage to give the entry screens a bit of character
// instead of just text + cards. Deliberately a single ellipse rather than a
// separate head circle + body shape stitched together -- two overlapping
// stroked outlines near the neck looked like a rendering glitch.
export default function Mascot({ className }) {
  return (
    <svg viewBox="0 0 120 120" className={className} aria-hidden="true">
      <g stroke="var(--text-primary)" strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round" fill="none">
        {/* arms, attached to the body's sides */}
        <path d="M34 68 16 82" />
        <path d="M86 68 104 82" />
        {/* one unified body/head shape */}
        <ellipse cx="60" cy="60" rx="32" ry="34" fill="var(--surface)" />
        {/* face */}
        <circle cx="49" cy="56" r="2.5" fill="var(--text-primary)" stroke="none" />
        <circle cx="71" cy="56" r="2.5" fill="var(--text-primary)" stroke="none" />
        <path d="M48 68c5 6 19 6 24 0" />
        <path d="M37 61c-2 3-2 6 0 8" />
        <path d="M83 61c2 3 2 6 0 8" />
      </g>
      {/* floating music note */}
      <g stroke="var(--accent)" strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round" fill="none">
        <path d="M92 18v22" />
        <ellipse cx="88" cy="42" rx="5" ry="3.5" fill="var(--accent)" stroke="none" transform="rotate(-15 88 42)" />
        <path d="M92 18c4-2 8-1 8 3" />
      </g>
    </svg>
  );
}
