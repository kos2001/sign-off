import { useLanguage } from './LanguageProvider';
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router";
import { useQueryClient } from "@tanstack/react-query";
import { api, setCsrfToken, type AuthState, type ProjectRole } from "../api";

const levels = { viewer: 0, editor: 1, approver: 2, owner: 3 };
interface AuthContextValue { state: AuthState; refresh: () => Promise<void>; logout: () => Promise<void>; changePassword: (current: string, replacement: string) => Promise<void>; can: (projectId: number, role: ProjectRole) => boolean }
const AuthContext = createContext<AuthContextValue | null>(null);
export function useAuth() { const value = useContext(AuthContext); if (!value) throw new Error("AuthProvider required"); return value; }

export function AuthProvider({ children }: { children: ReactNode }) {
  const { t } = useLanguage();
  const qc = useQueryClient();
  const [state, setState] = useState<AuthState | null>(null);
  const current = useRef<AuthState | null>(null);
  const generation = useRef(0);
  const [error, setError] = useState("");
  const apply = useCallback((next: AuthState) => {
    if (current.current?.user?.id !== next.user?.id || current.current?.mode !== next.mode || current.current?.user?.is_admin !== next.user?.is_admin || JSON.stringify(current.current?.memberships) !== JSON.stringify(next.memberships)) qc.clear();
    current.current = next;
    setCsrfToken(next.csrf_token);
    setState(next);
    setError("");
  }, [qc]);
  const refresh = useCallback(async () => {
    const version = ++generation.current;
    try { const next = await api.authSession(); if (version === generation.current) apply(next); }
    catch (error) { if (version === generation.current) setError((error as Error).message); }
  }, [apply]);
  useEffect(() => {
    void refresh();
    const expire = () => {
      generation.current++;
      apply({ mode: "required", user: null, csrf_token: null, memberships: {} });
    };
    const timer = setInterval(() => void refresh(), 60000);
    window.addEventListener("signoff-session-expired", expire);
    window.addEventListener("focus", refresh);
    window.addEventListener("signoff-auth-refresh", refresh);
    return () => { clearInterval(timer); window.removeEventListener("signoff-session-expired", expire); window.removeEventListener("focus", refresh); window.removeEventListener("signoff-auth-refresh", refresh); };
  }, [refresh, apply]);
  async function logout() {
    await api.logout();
    generation.current++;
    apply({ mode: "required", user: null, csrf_token: null, memberships: {} });
  }
  async function changePassword(currentPassword: string, replacement: string) {
    const next = await api.changePassword(currentPassword, replacement);
    generation.current++;
    apply(next);
  }
  if (!state) return <main className="p-8">{error ? <p role="alert">{t("연결 실패:", "Connection failed:")} {error} <button className="btn" onClick={refresh}>{t("다시 시도", "Retry")}</button></p> : <p role="status">{t("접속 상태 확인 중…", "Checking session…")}</p>}</main>;
  if (state.mode === "required" && !state.user) return <LoginForm onLogin={next => { generation.current++; apply(next); }} />;
  return <AuthContext.Provider value={{ state, refresh, logout, changePassword, can: (id, role) => state.mode === "local" || !!state.user?.is_admin || (levels[state.memberships[id]] ?? -1) >= levels[role] }}>
    <div key={`${state.mode}:${state.user?.id ?? "local"}:${state.user?.is_admin ?? false}:${JSON.stringify(state.memberships)}`}>{children}</div>
  </AuthContext.Provider>;
}

function LoginForm({ onLogin }: { onLogin: (state: AuthState) => void }) {
  const { t } = useLanguage();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  return <main className="min-h-screen flex items-center justify-center p-5"><form className="w-full max-w-sm rounded-xl border border-[var(--border)] bg-[var(--surface-1)] p-6 space-y-5" onSubmit={async e => {
    e.preventDefault(); setPending(true); setError("");
    try { onLogin(await api.login(username, password)); setPassword(""); }
    catch (error) { setError((error as Error).message); setPassword(""); }
    finally { setPending(false); }
  }}>
    <Link className="text-sm text-[var(--series-1)]" to="/guide">{t("서비스 소개 →", "Service guide →")}</Link>
    <div><h1 className="text-xl font-bold">{t("Sign-off Hub 로그인", "Sign in to Sign-off Hub")}</h1><p className="mt-2 text-sm text-[var(--text-secondary)]">{t("관리자가 발급한 계정으로 프로젝트에 접속하세요.", "Use an account issued by your administrator to access projects.")}</p></div>
    <label className="block text-sm">{t("사용자 이름", "Username")}<input autoFocus autoComplete="username" required maxLength={64} className="input w-full mt-2" value={username} onChange={e => setUsername(e.target.value)} disabled={pending} /></label>
    <label className="block text-sm">{t("비밀번호", "Password")}<input type="password" autoComplete="current-password" required maxLength={256} className="input w-full mt-2" value={password} onChange={e => setPassword(e.target.value)} disabled={pending} /></label>
    {error && <p role="alert" className="text-sm text-[var(--status-critical)]">{t("로그인 실패:", "Sign-in failed:")} {error}</p>}
    <button className="btn btn-primary w-full" disabled={pending}>{pending ? t("확인 중…", "Checking…") : t("로그인", "Sign in")}</button>
  </form></main>;
}
