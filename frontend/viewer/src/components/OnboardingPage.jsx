import { useEffect, useState } from "react";
import { useTranslation } from "../LanguageContext.jsx";
import Doodles from "./Doodles.jsx";
import Mascot from "./Mascot.jsx";

// Types `text` out one character at a time (like the reference site's
// hand-drawn hero title), replaying from scratch whenever `text` changes --
// which also covers revisiting this page via "更换使用者" navigating back here.
function useTypewriter(text, speedMs = 110) {
  const [length, setLength] = useState(0);
  const [done, setDone] = useState(false);

  useEffect(() => {
    setLength(0);
    setDone(false);
    let i = 0;
    const id = setInterval(() => {
      i += 1;
      setLength(i);
      if (i >= text.length) {
        clearInterval(id);
        setDone(true);
      }
    }, speedMs);
    return () => clearInterval(id);
  }, [text, speedMs]);

  return { display: text.slice(0, length), done };
}

// First screen a new (or logged-out) user sees: name + slogan only. Once a
// name is entered and saved, App.jsx skips straight to HomePage on future
// loads (see its localStorage-backed initial `page` state) -- this page is
// only for onboarding/switching identity, not a permanent nav destination.
export default function OnboardingPage({ username, onUsernameChange, onEnter }) {
  const { t } = useTranslation();
  const [error, setError] = useState(null);
  const { display: titleText, done: titleDone } = useTypewriter(t("appTitle"));

  const handleEnter = () => {
    if (!username.trim()) {
      setError(t("yourNameRequired"));
      return;
    }
    onEnter();
  };

  return (
    <div className="relative flex flex-col items-center justify-center gap-8 py-10 text-center">
      <Doodles />
      <Mascot className="h-24 w-24" />
      <div>
        <h1
          className={`text-5xl ${titleDone ? "title-bounce" : ""}`}
          style={{ color: "var(--accent)" }}
        >
          {titleText}
          {!titleDone && <span className="typewriter-cursor">|</span>}
        </h1>
        <p className={`mt-4 text-lg reveal-fade-up ${titleDone ? "visible" : ""}`} style={{ color: "var(--text-muted)" }}>
          {t("appSlogan")}
        </p>
      </div>

      <div className={`reveal-fade-up relative flex w-full max-w-sm flex-col gap-3 ${titleDone ? "visible" : ""}`}>
        <input
          type="text"
          className="rounded-lg border px-3 py-2 text-center text-sm"
          style={{ borderColor: "var(--accent)", color: "var(--text-primary)", background: "var(--surface)" }}
          value={username}
          onChange={(e) => onUsernameChange(e.target.value)}
          placeholder={t("yourNamePlaceholder")}
          onKeyDown={(e) => e.key === "Enter" && handleEnter()}
        />
        {error && (
          <div className="text-sm" style={{ color: "var(--status-wrong-pitch)" }}>{error}</div>
        )}
        <button
          className="sketch-btn px-4 py-2 text-sm font-medium"
          style={{ background: "var(--accent)", color: "var(--accent-contrast)" }}
          onClick={handleEnter}
        >
          {t("onboardingEnter")}
        </button>
      </div>
    </div>
  );
}
