export interface Company {
  id: string;
  name: string;
  error_schema_json: string | null;
  created_at: string;
  updated_at: string;
}

export interface FeatureTeam {
  id: string;
  company_id: string;
  name: string;
  tech_lead: string | null;
  created_at: string;
  updated_at: string;
  deleted_at: string | null;
}

export interface API {
  id: string;
  team_id: string;
  name: string;
  description: string | null;
  point_of_contact: string | null;
  created_at: string;
  updated_at: string;
  deleted_at: string | null;
}

export interface Endpoint {
  id: string;
  api_id: string;
  path: string;
  http_method: string;
  business_function: string | null;
  created_at: string;
  updated_at: string;
  deleted_at: string | null;
}

export interface EndpointVariant {
  id: string;
  endpoint_id: string;
  client_type: string;
  request_body_json: string | null;
  response_200_json: string | null;
  created_at: string;
  updated_at: string;
  deleted_at: string | null;
}

export interface Triple {
  id: string;
  subject: string;
  relation: string;
  object: string;
  scope: string;
  source_id: string;
  source_type: string;
  committed: boolean;
  pending_erasure: boolean;
  // True for request_body/response_200 bodies: served from Postgres via retrieval,
  // never pushed to the model. These stay committed=false forever, so they must not
  // be treated as ordinary "pending" (they can't be pushed).
  retrieval_only: boolean;
  created_at: string;
  updated_at: string;
}

export type JobStatus = "PENDING" | "QUEUED" | "RUNNING" | "COMPLETED" | "FAILED";
export type JobType = "edit_rome" | "edit_memit" | "erase_elm" | "rollback";

export interface EditJob {
  id: string;
  status: JobStatus;
  job_type: JobType;
  triple_ids: string[];
  submitted_at: string;
  started_at: string | null;
  completed_at: string | null;
  error_message: string | null;
  checkpoint_path: string | null;
}

export type JobStageStatus = "pending" | "running" | "done" | "failed";

export interface JobStageEvent {
  event: "STARTED" | "COMPLETED" | "FAILED" | "PROGRESS";
  message: string | null;
  created_at: string;
}

export interface JobStage {
  key: string;
  label: string;
  status: JobStageStatus;
  started_at: string | null;
  completed_at: string | null;
  traceback: string | null;
  events: JobStageEvent[];
}

export interface JobStagesResponse {
  job_id: string;
  job_type: JobType;
  status: JobStatus;
  stages: JobStage[];
}

export interface ModelCheckpoint {
  id: string;
  path: string;
  created_at: string;
  job_id: string | null;
  is_active: boolean;
}

export interface ModelStatus {
  model_loaded: boolean;
  active_checkpoint: ModelCheckpoint | null;
  total_checkpoints: number;
}

export type IncidentSeverity = "low" | "medium" | "high" | "critical";

export interface IncidentBriefRequest {
  title: string;
  severity: IncidentSeverity;
  signal_source: string | null;
  service_hint: string | null;
  api_hint: string | null;
  http_method: string | null;
  path: string | null;
  symptom: string;
}

export interface IncidentDeterministicSummary {
  owner_team: string | null;
  tech_lead: string | null;
  point_of_contact: string | null;
  api_name: string | null;
  endpoint: string | null;
  business_function: string | null;
}

export interface IncidentContext {
  matched_subjects: string[];
  ownership_facts: string[];
  endpoint_facts: string[];
  behavior_facts: string[];
  body_facts: string[];
  deterministic_summary: IncidentDeterministicSummary;
}

export interface IncidentBriefQueuedResponse {
  request_id: string;
  status: "QUEUED";
  stream_url: string;
  context: IncidentContext;
}

export type ChatRole = "user" | "assistant";
export type ChatMessageStatus = "complete" | "streaming" | "error";

export interface ChatSession {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface ChatGenParams {
  max_new_tokens?: number;
  temperature?: number;
  top_p?: number;
  repetition_penalty?: number;
  no_repeat_ngram_size?: number;
  // RAG facts injected into the prompt for this turn (assistant rows).
  retrieved?: string[];
}

export interface ChatMessage {
  id: string;
  session_id: string;
  role: ChatRole;
  content: string;
  gen_params: ChatGenParams | null;
  checkpoint_id: string | null;
  status: ChatMessageStatus;
  created_at: string;
}

export interface ChatSessionDetail extends ChatSession {
  messages: ChatMessage[];
}

export interface ChatSendResponse {
  user_message_id: string;
  assistant_message_id: string;
  stream_url: string;
}
