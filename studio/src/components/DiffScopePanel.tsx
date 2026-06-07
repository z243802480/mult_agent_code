import React from "react";
import type { GitStatusPayload } from "../types";
import type { TurnDiffScope } from "../turnDiff";
import { DiffScopeToolbar } from "../features/inspector/diff/DiffScopeToolbar";
import { DiffFileList } from "../features/inspector/diff/DiffFileList";

/** Stacked layout wrapper — smoke tests and legacy imports. Primary UI uses DiffReviewPane. */
export function DiffScopePanel({
  gitStatus,
  loading,
  selectedPath,
  scopes,
  activeScopeId,
  onSelectScope,
  onRefresh,
  onSelectChange,
}: {
  gitStatus: GitStatusPayload | null;
  loading: boolean;
  selectedPath: string | null;
  scopes: TurnDiffScope[];
  activeScopeId: string;
  onSelectScope: (scopeId: string) => void;
  onRefresh: () => void;
  onSelectChange: (path: string) => void;
}) {
  const activeScope = scopes.find((scope) => scope.id === activeScopeId) ?? scopes[0];

  return (
    <section className="gitChangesPanel">
      <DiffScopeToolbar
        gitStatus={gitStatus}
        loading={loading}
        scopes={scopes}
        activeScopeId={activeScopeId}
        onSelectScope={onSelectScope}
        onRefresh={onRefresh}
      />
      <DiffFileList
        gitStatus={gitStatus}
        activeScope={activeScope}
        selectedPath={selectedPath}
        onSelectChange={onSelectChange}
      />
    </section>
  );
}
