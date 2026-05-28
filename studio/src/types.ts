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
  runtimeRoot: string;
};

export type OverviewPayload = {
  ok: boolean;
  workspace: string;
  runtimeRoot: string;
  gateStatus?: AnyRecord;
  doctor?: AnyRecord;
  packageCheck?: AnyRecord;
  runs?: AnyRecord[];
  modelRoutes?: AnyRecord[];
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
  run_loop_summary?: AnyRecord;
  final_report_summary?: AnyRecord;
  model_route_timeline?: AnyRecord;
  goal_policy?: AnyRecord;
  model_calls?: AnyRecord[];
  task_execution_evidence?: AnyRecord[];
  worker_results?: AnyRecord[];
  validation_results?: AnyRecord[];
  events?: AnyRecord[];
  legacy_events?: AnyRecord[];
  timeline_events_source?: "user_progress" | "events";
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
