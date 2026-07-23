import { createContext, useCallback, useContext, useMemo, useState } from "react";
import { DEFAULT_LANGUAGE, LANGUAGES, STORAGE_KEY, translate } from "./i18n";

const LanguageContext = createContext(null);

function readStoredLanguage() {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    return stored === LANGUAGES.EN || stored === LANGUAGES.ZH ? stored : DEFAULT_LANGUAGE;
  } catch {
    return DEFAULT_LANGUAGE;
  }
}

export function LanguageProvider({ children }) {
  const [lang, setLangState] = useState(readStoredLanguage);

  const setLang = useCallback((next) => {
    setLangState(next);
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // localStorage unavailable (private mode etc.) -- language just won't persist
    }
  }, []);

  const toggleLang = useCallback(() => {
    setLang(lang === LANGUAGES.ZH ? LANGUAGES.EN : LANGUAGES.ZH);
  }, [lang, setLang]);

  const t = useCallback((key, vars) => translate(key, lang, vars), [lang]);

  const value = useMemo(() => ({ lang, setLang, toggleLang, t }), [lang, setLang, toggleLang, t]);

  return <LanguageContext.Provider value={value}>{children}</LanguageContext.Provider>;
}

export function useTranslation() {
  const ctx = useContext(LanguageContext);
  if (!ctx) throw new Error("useTranslation must be used within a LanguageProvider");
  return ctx;
}
