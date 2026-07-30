import { useMemo } from "react";
import { useTranslation } from "../LanguageContext.jsx";
import { getPostureComparison } from "../utils/posture.js";

export default function PostureComparison({ summary }) {
  const { t } = useTranslation();
  const comparison = useMemo(() => getPostureComparison(summary), [summary]);
  if (!comparison) return null;

  const errorLabel = t(comparison.errorLabelKey);

  return (
    <section className="posture-comparison" aria-labelledby="posture-comparison-title">
      <h3 id="posture-comparison-title" className="panel-heading">
        {t("postureComparisonTitle")}
      </h3>
      <p className="posture-comparison__intro">
        {t("postureComparisonIntro", {
          score: comparison.motionScore.toFixed(1),
          label: errorLabel,
        })}
      </p>

      <div className="posture-demo-grid">
        <figure className="posture-demo-card posture-demo-card--error">
          <img
            src={comparison.errorSrc}
            alt={t("postureErrorGifAlt", { label: errorLabel })}
            className="posture-demo-card__gif"
            loading="lazy"
          />
          <figcaption>
            <span className="posture-demo-card__eyebrow">{t("postureMostFrequentError")}</span>
            <strong>{errorLabel}</strong>
            <span>{t("postureOccurrences", { count: comparison.errorCount })}</span>
          </figcaption>
        </figure>

        <figure className="posture-demo-card posture-demo-card--normal">
          <img
            src={comparison.normalSrc}
            alt={t("postureNormalGifAlt")}
            className="posture-demo-card__gif"
            loading="lazy"
          />
          <figcaption>
            <span className="posture-demo-card__eyebrow">{t("postureRecommendedExample")}</span>
            <strong>{t("postureLabelNormal")}</strong>
            <span>{t("postureNormalHint")}</span>
          </figcaption>
        </figure>
      </div>
    </section>
  );
}
