// Scattered hand-drawn background decorations -- purely cosmetic, so only
// used on the low-density onboarding/home screens, never on data-heavy
// pages (scoring, history, notation) where they'd just be visual noise.
const ICONS = {
  star: "M12 2l2.4 6.6L21 10l-5 4.4L17.4 21 12 17.3 6.6 21 8 14.4 3 10l6.6-1.4z",
  heart: "M12 21s-7-4.5-9.5-9A5.5 5.5 0 0 1 12 6a5.5 5.5 0 0 1 9.5 6c-2.5 4.5-9.5 9-9.5 9z",
  spark: "M12 2v6M12 16v6M2 12h6M16 12h6M5 5l3 3M16 16l3 3M19 5l-3 3M8 16l-3 3",
};

const DEFAULT_ITEMS = [
  { icon: "star", top: "8%", left: "6%", size: 26, rotate: -12 },
  { icon: "heart", top: "70%", left: "4%", size: 22, rotate: 10 },
  { icon: "spark", top: "15%", left: "92%", size: 24, rotate: 0 },
  { icon: "star", top: "80%", left: "90%", size: 18, rotate: 20 },
  { icon: "spark", top: "45%", left: "2%", size: 16, rotate: -20 },
];

export default function Doodles({ items = DEFAULT_ITEMS }) {
  return (
    <div className="pointer-events-none absolute inset-0 overflow-hidden" aria-hidden="true">
      {items.map((item, i) => (
        <svg
          key={i}
          viewBox="0 0 24 24"
          fill="none"
          stroke="var(--border)"
          strokeWidth={1.4}
          strokeLinecap="round"
          strokeLinejoin="round"
          style={{
            position: "absolute",
            top: item.top,
            left: item.left,
            width: item.size,
            height: item.size,
            transform: `rotate(${item.rotate}deg)`,
            opacity: 0.6,
          }}
        >
          <path d={ICONS[item.icon]} />
        </svg>
      ))}
    </div>
  );
}
