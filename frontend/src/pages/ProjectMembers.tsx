import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router";
import { api, type ProjectRole } from "../api";
import { useAuth } from "../components/AuthProvider";
import { formatDateTime, tr, useLanguage } from "../components/LanguageProvider";

export const ROLE_LABELS: Record<ProjectRole, string> = {
  get viewer() { return tr("열람자", "Viewer"); },
  get editor() { return tr("편집자", "Editor"); },
  get approver() { return tr("승인자", "Approver"); },
  get owner() { return tr("소유자", "Owner"); },
};
export default function ProjectMembers() {
  const id = Number(useParams().id);
  const auth = useAuth();
  const { t } = useLanguage();
  const qc = useQueryClient();
  const [username, setUsername] = useState("");
  const [role, setRole] = useState<ProjectRole>("viewer");
  const members = useQuery({ queryKey: ["members", id], queryFn: () => api.members(id), enabled: auth.can(id, "owner") && auth.state.mode === "required" });
  const history = useInfiniteQuery({ queryKey: ["member-history", id], queryFn: ({ pageParam }) => api.memberHistory(id, pageParam), initialPageParam: undefined as number | undefined, getNextPageParam: page => page.next_before_id ?? undefined, enabled: auth.can(id, "owner") && auth.state.mode === "required" });
  const changed = async () => { await qc.invalidateQueries({ queryKey: ["member-history", id] }); await qc.invalidateQueries({ queryKey: ["members", id] }); await auth.refresh(); };
  const save = useMutation({ mutationFn: () => api.setMember(id, username.trim(), role), onSuccess: async () => { setUsername(""); await changed(); } });
  const remove = useMutation({ mutationFn: (userId: number) => api.removeMember(id, userId), onSuccess: changed });
  if (!auth.can(id, "owner") || auth.state.mode === "local") return <p>{t("프로젝트 소유자 권한이 필요합니다.", "Project owner permission is required.")} <Link className="underline" to={`/projects/${id}`}>{t("프로젝트로", "Back to project")}</Link></p>;
  return <section className="space-y-5 max-w-3xl">
    <header><Link className="text-sm underline" to={`/projects/${id}`}>{t("프로젝트로", "Back to project")}</Link><h1 className="text-xl font-bold mt-2">{t("프로젝트 접근 권한", "Project access")}</h1></header>
    <p className="text-sm">{t("열람자는 조회, 편집자는 런 등록·수정과 위반 수정 처리, 승인자는 웨이버 승인·해제, 소유자는 구성원 관리를 할 수 있습니다. 각 역할은 앞선 역할의 권한을 포함합니다.", "Viewers can browse; editors can register and edit runs and mark violations fixed; approvers can approve and revoke waivers; owners can manage members. Each role includes the permissions of the roles before it.")}</p>
    <form className="flex flex-wrap items-end gap-3" onSubmit={e => { e.preventDefault(); save.mutate(); }}>
      <label className="text-sm">{t("계정 이름", "Account name")}<input className="input block mt-1" required maxLength={64} value={username} onChange={e => setUsername(e.target.value)} /></label>
      <label className="text-sm">{t("프로젝트 역할", "Project role")}<select className="input block mt-1" value={role} onChange={e => setRole(e.target.value as ProjectRole)}>{Object.entries(ROLE_LABELS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
      <button className="btn btn-primary" disabled={save.isPending || remove.isPending}>{t("권한 저장", "Save access")}</button>
    </form>
    <p className="text-xs text-[var(--text-secondary)]">{t("기존 계정 이름을 입력하세요. 이미 등록된 구성원은 선택한 역할로 변경됩니다.", "Enter an existing account name. Members already on the project are changed to the selected role.")}</p>
    {(save.isError || remove.isError) && <p role="alert">{save.error?.message ?? remove.error?.message}</p>}
    {members.isPending ? <p role="status">{t("구성원 불러오는 중…", "Loading members…")}</p> : members.isError ? <p role="alert">{members.error.message} <button className="btn" onClick={() => members.refetch()}>{t("다시 시도", "Retry")}</button></p> : <ul className="space-y-2">{members.data.map(member => <li key={member.user_id} className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-[var(--border)] p-3">
      <span>{member.username} · {ROLE_LABELS[member.role]}{member.disabled ? t(" · 비활성 계정", " · Disabled account") : ""}</span>
      <button className="btn btn-ghost" disabled={remove.isPending || save.isPending || (member.user_id === auth.state.user?.id && !auth.state.user.is_admin)} onClick={() => remove.mutate(member.user_id)} aria-label={t(`${member.username} 접근 권한 제거`, `Remove access for ${member.username}`)}>{t("권한 제거", "Remove access")}</button>
    </li>)}</ul>}
    <section className="space-y-3 border-t border-[var(--border)] pt-5" aria-label={t("권한 변경 이력", "Access change history")}>
      <h2 className="text-base font-semibold">{t("권한 변경 이력", "Access change history")}</h2>
      <p className="text-xs text-[var(--text-secondary)]">{t("이력 기능 도입 이후의 변경을 기록합니다. 기존 구성원의 과거 권한과 처리자는 소급 추정하지 않습니다.", "Changes are recorded since history tracking was introduced. Earlier roles and actors for existing members are not inferred retroactively.")}</p>
      {history.isPending ? <p role="status">{t("이력 불러오는 중…", "Loading history…")}</p> : history.isError ? <p role="alert">{history.error.message} <button className="btn" onClick={() => history.refetch()}>{t("다시 시도", "Retry")}</button></p> : <>
        {history.data.pages[0].items.length === 0 ? <p className="text-sm">{t("기록된 권한 변경이 없습니다.", "No access changes recorded.")}</p> : <ol className="space-y-3">{history.data.pages.flatMap(page => page.items).map(event => <li key={event.id} className="rounded-lg bg-[var(--surface-1)] p-3 text-sm space-y-1">
          <p className="font-medium break-all">{event.subject_username} · {event.before_role ? ROLE_LABELS[event.before_role] : t("권한 없음", "No access")} → {event.after_role ? ROLE_LABELS[event.after_role] : t("권한 없음", "No access")}</p>
          <p className="text-xs text-[var(--text-secondary)]">{event.actor_user_id ? t(`${event.actor} · 로그인 계정`, `${event.actor} · Signed-in account`) : event.source === "operator" ? t("운영 CLI · 계정 인증 없음", "Operator CLI · No account authentication") : t("로컬 모드 · 계정 인증 없음", "Local mode · No account authentication")} · {formatDateTime(event.created_at)}</p>
        </li>)}</ol>}
        {history.hasNextPage && <button className="btn btn-ghost" disabled={history.isFetchingNextPage} onClick={() => history.fetchNextPage()}>{history.isFetchingNextPage ? t("불러오는 중…", "Loading…") : t("이전 권한 이력 더 보기", "Show earlier access history")}</button>}
      </>}
    </section>
  </section>;
}
