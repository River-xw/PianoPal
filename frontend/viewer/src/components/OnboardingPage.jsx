import { useState } from "react";
import { useTranslation } from "../LanguageContext.jsx";

// First screen a new (or logged-out) user sees: name + slogan only, blue
// accent per the product spec's "引导页（主色调：蓝色）". Once a name is
// entered and saved, App.jsx skips straight to HomePage on future loads
// (see its localStorage-backed initial `page` state) -- this page is only
// for onboarding/switching identity, not a permanent nav destination.
export default function OnboardingPage({ username, onUsernameChange, onEnter }) {
  const { t } = useTranslation();
  const [error, setError] = useState(null);

  const handleEnter = () => {
    if (!username.trim()) {
      setError(t("yourNameRequired"));
      return;
    }
    onEnter();
  };

  return (
    <div className="flex min-h-[70vh] flex-col items-center justify-center gap-8 py-10 text-center">
      <div>
        <h1 className="text-4xl font-bold" style={{ color: "var(--accent)" }}>{t("appTitle")}</h1>
        <p className="mt-3 text-base" style={{ color: "var(--text-muted)" }}>{t("appSlogan")}</p>
      </div>

      <div className="flex w-full max-w-sm flex-col gap-3">
        <input
          type="text"
          className="rounded-lg border px-3 py-2 text-center text-sm"
          style={{ borderColor: "var(--accent)", color: "var(--text-primary)", background: "transparent" }}
          value={username}
          onChange={(e) => onUsernameChange(e.target.value)}
          placeholder={t("yourNamePlaceholder")}
          onKeyDown={(e) => e.key === "Enter" && handleEnter()}
        />
        {error && (
          <div className="text-sm" style={{ color: "var(--status-wrong-pitch)" }}>{error}</div>
        )}
        <button
          className="rounded-lg px-4 py-2 text-sm font-medium"
          style={{ background: "var(--accent)", color: "var(--accent-contrast)" }}
          onClick={handleEnter}
        >
          {t("onboardingEnter")}
        </button>
      </div>
    </div>
  );
}
