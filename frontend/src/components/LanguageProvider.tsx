import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react';

export type Language = 'ko' | 'en';
const storageKey = 'signoff-language';
function storedLanguage(): Language {
  try { return (localStorage.getItem(storageKey) ?? localStorage.getItem('signoff-guide-language')) === 'en' ? 'en' : 'ko'; }
  catch { return 'ko'; }
}

// Mirrors the provider state for code outside React (API errors, shared label
// tables). Updated before the provider re-renders so render-time calls agree.
let activeLanguage: Language = storedLanguage();
function applyLanguage(next: Language) {
  activeLanguage = next;
  document.documentElement.lang = next;
}

/** Picks the active-language text; for modules that cannot call useLanguage. */
export function tr(ko: string, en: string) {
  return activeLanguage === 'ko' ? ko : en;
}

export function localeOf(language: Language = activeLanguage) {
  return language === 'ko' ? 'ko-KR' : 'en-US';
}

/** Server timestamps without an offset are UTC. */
export function parseServerDate(value: string | number | Date) {
  if (typeof value !== 'string') return new Date(value);
  return new Date(/[Zz]|[+-]\d\d:\d\d$/.test(value) || !/T|\d:\d/.test(value) ? value : `${value}Z`);
}

export function formatDateTime(value: string | number | Date) {
  return parseServerDate(value).toLocaleString(localeOf());
}

export function formatNumber(value: number, options?: Intl.NumberFormatOptions) {
  return value.toLocaleString(localeOf(), options);
}

const LanguageContext = createContext<{ language: Language; setLanguage: (language: Language) => void } | null>(null);
export function LanguageProvider({ children }: { children: ReactNode }) {
  const [language, updateLanguage] = useState<Language>(activeLanguage);
  const setLanguage = useCallback((next: Language) => {
    applyLanguage(next);
    updateLanguage(next);
    try { localStorage.setItem(storageKey, next); } catch { /* Works without browser storage. */ }
  }, []);
  useEffect(() => { applyLanguage(language); }, [language]);
  useEffect(() => {
    const sync = (event: StorageEvent) => {
      if (event.key === storageKey || event.key === null) {
        const next = storedLanguage();
        applyLanguage(next);
        updateLanguage(next);
      }
    };
    window.addEventListener('storage', sync);
    return () => window.removeEventListener('storage', sync);
  }, []);
  return <LanguageContext.Provider value={{ language, setLanguage }}>{children}</LanguageContext.Provider>;
}
export function useLanguage() {
  const context = useContext(LanguageContext);
  if (!context) throw new Error('LanguageProvider required');
  return { ...context, locale: localeOf(context.language), t: (ko: string, en: string) => context.language === 'ko' ? ko : en };
}
