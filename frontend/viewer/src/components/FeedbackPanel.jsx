import { useMemo } from "react";
import { generateFeedback } from "../utils/feedback";
import { useTranslation } from "../LanguageContext.jsx";
import PostureComparison from "./PostureComparison.jsx";

const STATUS_VAR = {
  timing_off: "--status-timing-off",
  wrong_pitch: "--status-wrong-pitch",
  missed: "--status-missed",
  extra: "--status-extra",
};

export default function FeedbackPanel({ notes, summary }) {
  const { t, lang } = useTranslation();
  const feedback = useMemo(() => generateFeedback(notes, summary, lang), [notes, summary, lang]);
  const passed = summary.score >= 60;

  return (
    <div className="sketch-card-alt p-5">
      <div className="panel-heading mb-4">
        {t("feedbackTitle")}
      </div>

      <div className="result-spirit-feedback">
        <div className="sprite-paper sprite-paper--result">
          <img
            src={passed ? "/assets/spirit-happy.png" : "/assets/spirit-sad.png"}
            alt=""
            className="result-spirit-feedback__image"
            aria-hidden="true"
          />
        </div>
        <div className="result-spirit-feedback__bubble">
          <div className="result-spirit-feedback__lead">
            {t(passed ? "spriteResultHappy" : "spriteResultSad")}
          </div>
          <p>{feedback.motion}</p>
        </div>
      </div>

      <PostureComparison summary={summary} />

      {feedback.overall && (
        <p className="mb-4 mt-4" style={{ color: "var(--text-secondary)" }}>
          {feedback.overall}
        </p>
      )}

      {feedback.items.length > 0 && (
        <ul className="flex flex-col gap-3">
          {feedback.items.map((item) => (
            <li key={item.key} className="flex items-start gap-2">
              <span
                className="mt-2 inline-block h-2 w-2 flex-shrink-0 rounded-full"
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
