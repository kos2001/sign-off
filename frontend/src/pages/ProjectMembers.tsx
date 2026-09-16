import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router";
import { api, type ProjectRole } from "../api";
import { useAuth } from "../components/AuthProvider";

export const ROLE_LABELS: Record<ProjectRole, string> = { viewer: "열람자", editor: "편집자", approver: "승인자", owner: "소유자" };
export default function ProjectMembers() {
  const id = Number(useParams().id);
  const auth = useAuth();
  const qc = useQueryClient();
  const [username, setUsername] = useState("");
  const [role, setRole] = useState<ProjectRole>("viewer");
  const members = useQuery({ queryKey: ["members", id], queryFn: () => api.members(id), enabled: auth.can(id, "owner") && auth.state.mode === "required" });
  const history = useInfiniteQuery({ queryKey: ["member-history", id], queryFn: ({ pageParam }) => api.memberHistory(id, pageParam), initialPageParam: undefined as number | undefined, getNextPageParam: page => page.next_before_id ?? undefined, enabled: auth.can(id, "owner") && auth.state.mode === "required" });
  const changed = async () => { await qc.invalidateQueries({ queryKey: ["member-history", id] }); await qc.invalidateQueries({ queryKey: ["members", id] }); await auth.refresh(); };
  const save = useMutation({ mutationFn: () => api.setMember(id, username.trim(), role), onSuccess: async () => { setUsername(""); await changed(); } });
  const remove = useMutation({ mutationFn: (userId: number) => api.removeMember(id, userId), onSuccess: changed });
  if (!auth.can(id, "owner") || auth.state.mode === "local") return <p>프로젝트 소유자 권한이 필요합니다. <Link className="underline" to={`/projects/${id}`}>프로젝트로</Link></p>;
  return <section className="space-y-5 max-w-3xl">
    <header><Link className="text-sm underline" to={`/projects/${id}`}>프로젝트로</Link><h1 className="text-xl font-bold mt-2">프로젝트 접근 권한</h1></header>
    <p className="text-sm">열람자는 조회, 편집자는 런 등록·수정과 위반 수정 처리, 승인자는 웨이버 승인·해제, 소유자는 구성원 관리를 할 수 있습니다. 각 역할은 앞선 역할의 권한을 포함합니다.</p>
    <form className="flex flex-wrap items-end gap-3" onSubmit={e => { e.preventDefault(); save.mutate(); }}>
      <label className="text-sm">계정 이름<input className="input block mt-1" required maxLength={64} value={username} onChange={e => setUsername(e.target.value)} /></label>
      <label className="text-sm">프로젝트 역할<select className="input block mt-1" value={role} onChange={e => setRole(e.target.value as ProjectRole)}>{Object.entries(ROLE_LABELS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
      <button className="btn btn-primary" disabled={save.isPending || remove.isPending}>권한 저장</button>
    </form>
    <p className="text-xs text-[var(--text-secondary)]">기존 계정 이름을 입력하세요. 이미 등록된 구성원은 선택한 역할로 변경됩니다.</p>
    {(save.isError || remove.isError) && <p role="alert">{save.error?.message ?? remove.error?.message}</p>}
    {members.isPending ? <p role="status">구성원 불러오는 중…</p> : members.isError ? <p role="alert">{members.error.message} <button className="btn" onClick={() => members.refetch()}>다시 시도</button></p> : <ul className="space-y-2">{members.data.map(member => <li key={member.user_id} className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-[var(--border)] p-3">
      <span>{member.username} · {ROLE_LABELS[member.role]}{member.disabled ? " · 비활성 계정" : ""}</span>
      <button className="btn btn-ghost" disabled={remove.isPending || save.isPending || (member.user_id === auth.state.user?.id && !auth.state.user.is_admin)} onClick={() => remove.mutate(member.user_id)} aria-label={`${member.username} 접근 권한 제거`}>권한 제거</button>
    </li>)}</ul>}
    <section className="space-y-3 border-t border-[var(--border)] pt-5" aria-label="권한 변경 이력">
      <h2 className="text-base font-semibold">권한 변경 이력</h2>
      <p className="text-xs text-[var(--text-secondary)]">이력 기능 도입 이후의 변경을 기록합니다. 기존 구성원의 과거 권한과 처리자는 소급 추정하지 않습니다.</p>
      {history.isPending ? <p role="status">이력 불러오는 중…</p> : history.isError ? <p role="alert">{history.error.message} <button className="btn" onClick={() => history.refetch()}>다시 시도</button></p> : <>
        {history.data.pages[0].items.length === 0 ? <p className="text-sm">기록된 권한 변경이 없습니다.</p> : <ol className="space-y-3">{history.data.pages.flatMap(page => page.items).map(event => <li key={event.id} className="rounded-lg bg-[var(--surface-1)] p-3 text-sm space-y-1">
          <p className="font-medium break-all">{event.subject_username} · {event.before_role ? ROLE_LABELS[event.before_role] : "권한 없음"} → {event.after_role ? ROLE_LABELS[event.after_role] : "권한 없음"}</p>
          <p className="text-xs text-[var(--text-secondary)]">{event.actor_user_id ? `${event.actor} · 로그인 계정` : event.source === "operator" ? "운영 CLI · 계정 인증 없음" : "로컬 모드 · 계정 인증 없음"} · {new Date(/[Zz]|[+-]\d\d:\d\d$/.test(event.created_at) ? event.created_at : `${event.created_at}Z`).toLocaleString()}</p>
        </li>)}</ol>}
        {history.hasNextPage && <button className="btn btn-ghost" disabled={history.isFetchingNextPage} onClick={() => history.fetchNextPage()}>{history.isFetchingNextPage ? "불러오는 중…" : "이전 권한 이력 더 보기"}</button>}
      </>}
    </section>
  </section>;
}
