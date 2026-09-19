import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react';

export type Language = 'ko' | 'en';
const storageKey = 'signoff-language';
function storedLanguage(): Language {
  try { return (localStorage.getItem(storageKey) ?? localStorage.getItem('signoff-guide-language')) === 'en' ? 'en' : 'ko'; }
  catch { return 'ko'; }
}
const LanguageContext = createContext<{ language: Language; setLanguage: (language: Language) => void } | null>(null);
export function LanguageProvider({ children }: { children: ReactNode }) {
  const [language, updateLanguage] = useState<Language>(storedLanguage);
  const setLanguage = useCallback((next: Language) => {
    updateLanguage(next);
    try { localStorage.setItem(storageKey, next); } catch { /* Works without browser storage. */ }
  }, []);
  useEffect(() => { document.documentElement.lang = language; }, [language]);
  useEffect(() => {
    const sync = (event: StorageEvent) => {
      if (event.key === storageKey || event.key === null) updateLanguage(storedLanguage());
    };
    window.addEventListener('storage', sync);
    return () => window.removeEventListener('storage', sync);
  }, []);
  return <LanguageContext.Provider value={{ language, setLanguage }}>{children}</LanguageContext.Provider>;
}
export function useLanguage() {
  const context = useContext(LanguageContext);
  if (!context) throw new Error('LanguageProvider required');
  return { ...context, t: (ko: string, en: string) => context.language === 'ko' ? ko : en };
}
