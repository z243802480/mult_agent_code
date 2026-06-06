export type AnyRecord = Record<string, unknown>;

export type StudioSession = {
  session_id: string;
  title: string;
  workspace: string;
  created_at: string;
  updated_at: string;
};

export type StudioEvent = {
  event_id: string;
  session_id: string;
  type:
    | "user_message"
    | "intent_route"
    | "assistant_delta"
    | "reasoning_delta"
    | "model_start"
    | "model_delta"
    | "model_end"
    | "model_error"
    | "tool_start"
    | "tool_delta"
    | "tool_end"
    | "agent_turn"
    | "tool_observation"
    | "permission_request"
    | "file_changed"
    | "final_answer"
    | "error";
  status: "queued" | "running" | "waiting_user" | "completed" | "failed" | "blocked";
  title: string;
  summary: string;
  content_delta?: string;
  command?: string[];
  data?: AnyRecord;
  tool_call_id?: string;
  parent_event_id?: string;
  artifact_refs?: string[];
  evidence_refs?: string[];
  model_provider?: string;
  model_name?: string;
  model_tier?: string;
  model_route?: AnyRecord;
  intent_route?: AnyRecord;
  intent_audit?: AnyRecord;
  telemetry?: AnyRecord;
  file_changes?: AnyRecord[];
  runtime_channel?: string;
  runtime_event_type?: string;
  transcript_kind?: string;
  ui_intent?: string;
  actions?: AnyRecord[];
  source?: string;
  run_id?: string;
  job_id?: string;
  phase?: "understand" | "plan" | "execute" | "review" | "resume" | "result" | "next" | string;
  display_level?: "main" | "inspector";
  created_at: string;
};

export type WorkspaceFile = {
  path: string;
  size: number;
  modified_at: string;
};

export type FilePreview = {
  ok: boolean;
  path?: string;
  content?: string;
  error?: string;
};

export type SettingsPayload = {
  workMode: string;
  permissionMode: string;
  shell: string;
  streamMode: string;
  workspace: string;
  workspaceName?: string;
  runtimeRoot: string;
};

export type WorkspaceEntry = {
  workspace_id?: string;
  name?: string;
  workspace_root: string;
  output_root?: string;
  artifact_root?: string;
  last_opened_at?: string;
};

export type WorkspacesPayload = {
  ok: boolean;
  workspace: string;
  runtimeRoot: string;
  current_workspace_root?: string;
  recent_workspaces: WorkspaceEntry[];
};

export type OpenWorkspacePayload = {
  ok: boolean;
  workspace?: string;
  runtimeRoot?: string;
  workspace_name?: string;
  initialized?: boolean;
  error?: string;
};

export type BrowseWorkspacePayload = {
  ok: boolean;
  cancelled?: boolean;
  path?: string | null;
  error?: string;
};

export type OverviewPayload = {
  ok: boolean;
  workspace: string;
  runtimeRoot: string;
  diagnostics_loaded?: boolean;
  gateStatus?: AnyRecord;
  doctor?: AnyRecord;
  packageCheck?: AnyRecord;
  runs?: AnyRecord[];
  modelRoutes?: AnyRecord[];
  v0_2_rolling_validation?: AnyRecord;
  long_horizon?: AnyRecord;
  workflow?: {
    can_review?: boolean;
    can_accept?: boolean;
    workflow_state?: string;
    recommended_next_command?: string;
    next_actions?: string[];
  };
};

export type RunDetailPayload = {
  ok: boolean;
  error?: string;
  run_id?: string;
  run?: AnyRecord;
  cost_report?: AnyRecord;
  goal_spec?: AnyRecord;
  task_plan?: AnyRecord;
  task_plan_eval?: AnyRecord;
  agent_run_graph?: AnyRecord;
  agent_loop_run_summary?: AnyRecord;
  run_loop_summary?: AnyRecord;
  runtime_progress?: AnyRecord;
  main_action?: AnyRecord;
  decision_requests?: AnyRecord[];
  decisions?: AnyRecord[];
  decision_history?: AnyRecord[];
  worker_tree?: AnyRecord;
  candidate_exports?: AnyRecord[];
  merge_gate_dry_runs?: AnyRecord[];
  candidate_promotions?: AnyRecord[];
  promotion_preview?: AnyRecord;
  final_report_summary?: AnyRecord;
  model_route_timeline?: AnyRecord;
  goal_policy?: AnyRecord;
  model_calls?: AnyRecord[];
  task_execution_evidence?: AnyRecord[];
  worker_results?: AnyRecord[];
  validation_results?: AnyRecord[];
  events?: AnyRecord[];
  legacy_events?: AnyRecord[];
  raw_evidence?: AnyRecord;
  timeline_events_source?: "user_progress" | "events";
  timeline_default?: "user_progress" | "legacy_events_fallback";
  inspector_raw_evidence_source?: "raw_evidence";
  user_progress?: AnyRecord[];
  files?: WorkspaceFile[];
};

export type NarrativeStep = {
  id: string;
  label: string;
  title: string;
  summary: string;
  status: StudioEvent["status"];
  kind: "goal" | "thinking" | "plan" | "turn" | "tool" | "observation" | "result" | "repair" | "verification" | "final" | "error";
  events: StudioEvent[];
  defaultOpen: boolean;
};

export type RunNarrative = {
  steps: NarrativeStep[];
  report: {
    status: "running" | "completed" | "failed";
    headline: string;
    goal: string;
    modelEvents: number;
    toolEvents: number;
    evidenceRefs: number;
    artifactRefs: number;
    finalText: string;
  };
};
