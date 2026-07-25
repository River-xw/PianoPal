import { useEffect, useState } from "react";
import SummaryPanel from "./SummaryPanel";
import NotationView from "./NotationView";
import FeedbackPanel from "./FeedbackPanel";
import PianoRoll from "./PianoRoll";
import TimingStrip from "./TimingStrip";
import TrendChart from "./TrendChart";
import { useTranslation } from "../LanguageContext.jsx";
import { profileSummarySentence } from "../utils/profile";
import { downloadJson } from "../utils/download";

// Same sub_scores keys/labels SummaryPanel.jsx uses -- kept in sync with it.
const SUB_SCORE_LABEL_KEYS = {
  pitch: "pitchAccuracy",
  rhythm: "rhythmAccuracy",
  hand_shape: "handShapeScore",
};

function exportFilename(session) {
  return `${session.piece_title}_${session.started_at}.json`.replace(/[^\w\-.]+/g, "_");
}

// "我的" page: profile summary (总练习次数/近期平均分/常练曲目/一句话画像),
// this user's practice_sessions rows (backend.db.sqlite via GET
// /api/history) with filter/view/delete/export, a score trend chart, and a
// side-by-side sub-score comparison for any 2+ selected sessions. Renamed
// from HistoryPage.jsx -- scope grew past a plain list.
export default function MyPage({ username }) {
  const { t, lang } = useTranslation();
  const [sessions, setSessions] = useState([]);
  const [profile, setProfile] = useState(null);
  const [modeFilter, setModeFilter] = useState("");
  const [error, setError] = useState(null);
  const [detail, setDetail] = useState(null);
  const [selected, setSelected] = useState(() => new Set());

  const loadList = () => {
    const name = (username || "").trim();
    if (!name) return;
    const params = new URLSearchParams({ username: name });
    if (modeFilter) params.set("mode", modeFilter);
    fetch(`/api/history?${params.toString()}`, { cache: "no-store" })
      .then((res) => res.json())
      .then((data) => {
        setSessions(data.sessions || []);
        setProfile(data.profile || null);
        setError(null);
      })
      .catch(() => setError(t("historyLoadFailed")));
  };

  useEffect(loadList, [username, modeFilter]);

  const viewDetail = (sessionId) => {
    fetch(`/api/history/${sessionId}`, { cache: "no-store" })
      .then((res) => (res.ok ? res.json() : null))
      .then((parsed) => {
        if (parsed && parsed.summary && parsed.notes) setDetail(parsed);
      });
  };

  const exportSession = async (sessionId, session) => {
    const res = await fetch(`/api/history/${sessionId}`, { cache: "no-store" });
    if (!res.ok) return;
    downloadJson(await res.json(), exportFilename(session));
  };

  const deleteSession = async (sessionId) => {
    if (!window.confirm(t("historyDeleteConfirm"))) return;
    await fetch(`/api/history/${sessionId}`, { method: "DELETE" });
    setSelected((prev) => {
      const next = new Set(prev);
      next.delete(sessionId);
      return next;
    });
    loadList();
  };

  const toggleSelected = (sessionId) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(sessionId)) next.delete(sessionId);
      else next.add(sessionId);
      return next;
    });
  };

  const compareSessions = sessions.filter((s) => selected.has(s.id) && s.summary);

  if (detail) {
    return (
      <div className="flex flex-col gap-4">
        <div className="flex items-center gap-2">
          <button
            className="rounded-lg border px-3 py-1.5 text-sm"
            style={{ borderColor: "var(--border)", color: "var(--text-secondary)" }}
            onClick={() => setDetail(null)}
          >
            {t("historyBackToList")}
          </button>
          <button
            className="rounded-lg border px-3 py-1.5 text-sm"
            style={{ borderColor: "var(--border)", color: "var(--text-secondary)" }}
            onClick={() => downloadJson(detail, exportFilename({ piece_title: detail.song_name || "session", started_at: Date.now() }))}
          >
            {t("historyExport")}
          </button>
        </div>
        <SummaryPanel summary={detail.summary} />
        <NotationView notes={detail.notes} />
        <FeedbackPanel notes={detail.notes} summary={detail.summary} />
        <PianoRoll notes={detail.notes} />
        <TimingStrip notes={detail.notes} />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl" style={{ color: "var(--text-primary)" }}>{t("navMe")}</h2>
        <select
          className="rounded-lg border px-3 py-1.5 text-sm"
          style={{ borderColor: "var(--border)", color: "var(--text-secondary)", background: "transparent" }}
          value={modeFilter}
          onChange={(e) => setModeFilter(e.target.value)}
        >
          <option value="">{t("historyFilterAll")}</option>
          <option value="learn">{t("navLearnMode")}</option>
          <option value="perform">{t("navPerformMode")}</option>
        </select>
      </div>

      {profile && (
        <div className="sketch-card tint-sky flex flex-col gap-1 px-5 py-4" style={{ border: "none" }}>
          <div className="flex flex-wrap items-center gap-x-6 gap-y-1 text-sm" style={{ color: "var(--text-secondary)" }}>
            <span>{t("recentSummaryTotal", { count: profile.total_sessions })}</span>
            {profile.recent_avg_score != null && (
              <span>{t("recentSummaryAvg", { score: profile.recent_avg_score.toFixed(1) })}</span>
            )}
          </div>
          <div className="text-sm" style={{ color: "var(--text-muted)" }}>{profileSummarySentence(profile, lang)}</div>
        </div>
      )}

      {error && (
        <div className="rounded-lg border px-3 py-2 text-sm" style={{ borderColor: "var(--status-wrong-pitch)", color: "var(--status-wrong-pitch)" }}>
          {error}
        </div>
      )}

      {sessions.length === 0 && !error && (
        <div className="text-sm" style={{ color: "var(--text-muted)" }}>{t("historyEmpty")}</div>
      )}

      <TrendChart sessions={sessions} />

      {sessions.length > 0 && (
        <div className="text-xs" style={{ color: "var(--text-muted)" }}>{t("compareSelectHint")}</div>
      )}

      <div className="flex flex-col gap-2">
        {sessions.map((s) => (
          <div
            key={s.id}
            className="flex flex-wrap items-center justify-between gap-3 rounded-lg border px-4 py-3"
            style={{ borderColor: "var(--border)" }}
          >
            <div className="flex items-center gap-3">
              {s.status === "completed" && (
                <input
                  type="checkbox"
                  checked={selected.has(s.id)}
                  onChange={() => toggleSelected(s.id)}
                />
              )}
              <div className="flex flex-col gap-0.5">
                <span className="text-sm font-medium" style={{ color: "var(--text-primary)" }}>{s.piece_title}</span>
                <span className="text-xs" style={{ color: "var(--text-muted)" }}>
                  {new Date(s.started_at).toLocaleString()} · {s.mode === "perform" ? t("navPerformMode") : t("navLearnMode")}
                </span>
              </div>
            </div>
            <div className="flex items-center gap-3">
              <span className="text-lg font-semibold" style={{ color: "var(--text-primary)" }}>
                {s.status === "completed" ? s.score.toFixed(1) : t("historyStatusError")}
              </span>
              {s.status === "completed" && (
                <>
                  <button
                    className="rounded-lg border px-3 py-1.5 text-xs"
                    style={{ borderColor: "var(--border)", color: "var(--text-secondary)" }}
                    onClick={() => viewDetail(s.id)}
                  >
                    {t("historyView")}
                  </button>
                  <button
                    className="rounded-lg border px-3 py-1.5 text-xs"
                    style={{ borderColor: "var(--border)", color: "var(--text-secondary)" }}
                    onClick={() => exportSession(s.id, s)}
                  >
                    {t("historyExport")}
                  </button>
                </>
              )}
              <button
                className="rounded-lg border px-3 py-1.5 text-xs"
                style={{ borderColor: "var(--status-wrong-pitch)", color: "var(--status-wrong-pitch)" }}
                onClick={() => deleteSession(s.id)}
              >
                {t("historyDelete")}
              </button>
            </div>
          </div>
        ))}
      </div>

      {compareSessions.length >= 2 && (
        <div className="sketch-card-alt overflow-x-auto p-4">
          <div className="panel-heading mb-3">{t("compareTitle")}</div>
          <table className="w-full text-left text-sm" style={{ color: "var(--text-secondary)" }}>
            <thead>
              <tr>
                <th className="pr-4 pb-2 font-medium" style={{ color: "var(--text-muted)" }}></th>
                {compareSessions.map((s) => (
                  <th key={s.id} className="pr-4 pb-2 font-medium">
                    {s.piece_title}
                    <div className="text-xs font-normal" style={{ color: "var(--text-muted)" }}>
                      {new Date(s.started_at).toLocaleDateString()}
                    </div>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              <tr>
                <td className="pr-4 py-1" style={{ color: "var(--text-muted)" }}>{t("historyScore")}</td>
                {compareSessions.map((s) => (
                  <td key={s.id} className="pr-4 py-1 font-semibold" style={{ color: "var(--text-primary)" }}>{s.score.toFixed(1)}</td>
                ))}
              </tr>
              {Object.entries(SUB_SCORE_LABEL_KEYS).map(([key, labelKey]) => (
                <tr key={key}>
                  <td className="pr-4 py-1" style={{ color: "var(--text-muted)" }}>{t(labelKey)}</td>
                  {compareSessions.map((s) => {
                    const value = s.summary?.sub_scores?.[key];
                    return (
                      <td key={s.id} className="pr-4 py-1">
                        {value != null ? value.toFixed(1) : "--"}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
