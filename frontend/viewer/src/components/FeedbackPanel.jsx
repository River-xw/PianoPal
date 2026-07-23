import { useMemo } from "react";
import { generateFeedback } from "../utils/feedback";
import { useTranslation } from "../LanguageContext.jsx";

const STATUS_VAR = {
  timing_off: "--status-timing-off",
  wrong_pitch: "--status-wrong-pitch",
  missed: "--status-missed",
  extra: "--status-extra",
};

export default function FeedbackPanel({ notes, summary }) {
  const { t, lang } = useTranslation();
  const feedback = useMemo(() => generateFeedback(notes, summary, lang), [notes, summary, lang]);

  return (
    <div className="rounded-xl border p-4" style={{ borderColor: "var(--border)", background: "var(--surface)" }}>
      <div className="mb-3 text-sm font-medium" style={{ color: "var(--text-primary)" }}>
        {t("feedbackTitle")}
      </div>

      {feedback.overall && (
        <p className="mb-3 text-sm" style={{ color: "var(--text-secondary)" }}>
          {feedback.overall}
        </p>
      )}

      {feedback.items.length > 0 && (
        <ul className="flex flex-col gap-2">
          {feedback.items.map((item) => (
            <li key={item.key} className="flex items-start gap-2 text-sm">
              <span
                className="mt-1.5 inline-block h-2 w-2 flex-shrink-0 rounded-full"
                style={{ background: `var(${STATUS_VAR[item.status]})` }}
              />
              <span style={{ color: "var(--text-secondary)" }}>{item.text}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
