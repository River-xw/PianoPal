export default function BrandLogo({ className = "", animated = false }) {
  return (
    <img
      src="/assets/pianopal-logo.png"
      alt="PianoPal"
      className={`brand-logo ${animated ? "brand-logo--animated" : ""} ${className}`}
    />
  );
}
