import { createContext, useContext, useState, type ReactNode } from "react";
import type { Violation, ViolationStatus } from "../api";

interface ReviewDraft {
  target: ViolationStatus | null;
  reviewVersion: number;
  reviewStatus: ViolationStatus;
  actor: string;
  reason: string;
}

const DraftContext = createContext<{
  drafts: Record<number, ReviewDraft>;
  update: (violation: Violation, patch: Partial<ReviewDraft>) => void;
} | null>(null);

const initial = (v: Violation): ReviewDraft => ({ target: null, reviewVersion: v.version, reviewStatus: v.status, actor: "", reason: "" });

/** In-memory drafts survive filtering/navigation, but are never written to browser storage. */
export function ReviewDraftProvider({ children }: { children: ReactNode }) {
  const [drafts, setDrafts] = useState<Record<number, ReviewDraft>>({});
  const update = (v: Violation, patch: Partial<ReviewDraft>) => {
    setDrafts(previous => ({ ...previous, [v.id]: { ...(previous[v.id] ?? initial(v)), ...patch } }));
  };
  return <DraftContext.Provider value={{ drafts, update }}>{children}</DraftContext.Provider>;
}

export function useReviewDraft(v: Violation) {
  const context = useContext(DraftContext);
  if (!context) throw new Error("ReviewDraftProvider is required");
  return [context.drafts[v.id] ?? initial(v), (patch: Partial<ReviewDraft>) => context.update(v, patch)] as const;
}
