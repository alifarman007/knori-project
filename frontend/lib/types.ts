/**
 * Wire types for `/api/v1` (plan.md §7).
 *
 * Field names are snake_case because that is what FastAPI sends; nothing is
 * renamed on the way in, so a mismatch shows up as a type error rather than a
 * silently empty screen. Once the backend exports OpenAPI, this file is the
 * thing that gets regenerated.
 */

export type Uuid = string;
/** RFC 3339, always with an offset. */
export type IsoDateTime = string;

/* -------------------------------------------------------------- errors */

/** One field the API rejected. `knori.core.errors.ValidationFailed` sends a list of these. */
export interface ProblemFieldError {
  field: string;
  message: string;
}

/** RFC 7807 problem+json, plus the fields KnoRI always adds. */
export interface ProblemDetail {
  type: string;
  title: string;
  status: number;
  detail?: string;
  instance?: string;
  /** Machine-readable code, e.g. "invite_required", "email_not_verified". */
  code?: string;
  /**
   * Form errors. The API sends a list of `{field, message}`; some handlers send
   * the older field -> messages map. `ApiError` normalises both to the map.
   */
  errors?: ProblemFieldError[] | Record<string, string[]>;
  /** Seconds, on a 429. */
  retry_after?: number;
  request_id?: string;
}

/* ---------------------------------------------------------------- page */

export interface Page<T> {
  items: T[];
  next_cursor: string | null;
}

/* -------------------------------------------------------------- account */

export type UserRole = "user" | "admin";
export type ChatStyle = "warm" | "direct";

export interface Me {
  id: Uuid;
  email: string;
  display_name: string;
  preferred_name: string | null;
  timezone: string;
  role: UserRole;
  email_verified: boolean;
  onboarding_complete: boolean;
  created_at: IsoDateTime;
}

export interface UserSettings {
  recognition_enabled: boolean;
  memory_enabled: boolean;
  max_recognitions_per_day: number;
  chat_style: ChatStyle;
}

/* --------------------------------------------------------- conversation */

export type ConversationKind = "chat" | "onboarding";
export type MessageRole = "user" | "assistant";
export type MessageStatus = "complete" | "streaming" | "partial" | "failed";

export interface Conversation {
  id: Uuid;
  kind: ConversationKind;
  title: string | null;
  is_incognito: boolean;
  message_count: number;
  last_message_at: IsoDateTime | null;
  archived_at: IsoDateTime | null;
  created_at: IsoDateTime;
}

export interface Message {
  id: Uuid;
  seq: number;
  role: MessageRole;
  content: string;
  status: MessageStatus;
  created_at: IsoDateTime;
}

/** Places a Recognition card inside a thread without faking a message. */
export interface ConversationEvent {
  id: Uuid;
  kind: "recognition";
  after_seq: number;
  recognition_id: Uuid;
}

export interface WelcomeBack {
  days_away: number;
  memories_added: number;
  new_recognitions: number;
}

/* --------------------------------------------------------- recognition */

export type RecognitionKind = "pattern" | "preference" | "value" | "tension";
export type RecognitionState =
  | "pending"
  | "presented"
  | "accepted"
  | "corrected"
  | "rejected"
  | "dismissed"
  | "withdrawn";
export type ConfidenceLabel = "likely" | "strong";
export type EvidenceRole = "supports" | "contradicts" | "context";
export type FeedbackAction = "accept" | "correct" | "reject" | "dismiss";
export type ReasonCode = "not_true" | "partly_true" | "outdated" | "too_personal" | "not_useful";

/**
 * One frozen piece of evidence. `quote_text` is verbatim from the person's own
 * message; when they delete that message the server scrubs the text to
 * "[deleted by you]" and nulls the offsets, keeping the row.
 */
export interface ProvenanceItem {
  id: Uuid;
  kind: "signal" | "assertion";
  role: EvidenceRole;
  weight: number;
  quote_text: string;
  quote_start: number | null;
  quote_end: number | null;
  message_id: Uuid | null;
  conversation_id: Uuid | null;
  conversation_title: string | null;
  seq: number | null;
  message_created_at: IsoDateTime | null;
  scrubbed: boolean;
  note: string | null;
  display_order: number;
  /** Built by the API: `/app/chat/{id}?m={seq}&hl={start}-{end}`. */
  deep_link?: string | null;
}

/** How sure KnoRI is, and the counts behind the sentence under every card. */
export interface RecognitionConfidence {
  value: number;
  label: ConfidenceLabel;
  /** Already written as a sentence by the API: "Based on 3 things … across 3 days". */
  plain: string;
  supports: number;
  contradicts: number;
  distinct_days: number;
  span_hours: number;
  deleted_sources: number;
}

export interface Recognition {
  id: Uuid;
  interpretation_id: Uuid;
  interpretation_version: number;
  kind: RecognitionKind;
  title: string;
  body: string;
  confidence: RecognitionConfidence;
  state: RecognitionState;
  supersedes_id: Uuid | null;
  created_at: IsoDateTime;
  presented_at: IsoDateTime | null;
  resolved_at: IsoDateTime | null;
  feedback_action: FeedbackAction | null;
  correction_effect_status: "pending" | "ready" | null;
}

export interface RecognitionFeedback {
  id: Uuid;
  action: FeedbackAction;
  correction_text: string | null;
  reason_code: ReasonCode | null;
  created_at: IsoDateTime;
  processed_at: IsoDateTime | null;
}

export interface CorrectionEffectItem {
  interpretation_id: Uuid;
  statement: string;
  before: { status: string; confidence: number };
  after: { status: string; confidence: number };
}

export interface CorrectionEffect {
  feedback_id: Uuid;
  status: "pending" | "ready";
  summary: string;
  effects: CorrectionEffectItem[];
  recognitions_withdrawn: Uuid[];
  recognitions_created: Uuid[];
  assertions_created: Uuid[];
  profile_before_text: string | null;
  profile_after_text: string | null;
}

export interface RecognitionDetail extends Recognition {
  explanation: string;
  /** Plain words for the confidence label, written by the API, not the client. */
  confidence_in_words: string;
  interpretation: {
    id: Uuid;
    version: number;
    kind: RecognitionKind;
    topic: string;
    statement: string;
  };
  provenance: ProvenanceItem[];
  feedback: RecognitionFeedback | null;
  correction_effect: CorrectionEffect | null;
}

export interface RecognitionSummary {
  new: number;
  accepted: number;
  corrected: number;
  rejected: number;
  dismissed: number;
  unread: number;
}

export interface FeedbackRequest {
  action: FeedbackAction;
  correction_text?: string;
  reason_code?: ReasonCode;
}

/* -------------------------------------------------------------- memory */

export type MemoryKind =
  | "fact"
  | "preference"
  | "goal"
  | "event"
  | "routine"
  | "constraint"
  | "relationship";
export type MemoryStatus = "active" | "superseded" | "retracted";
export type MemorySourceKind =
  | "extracted"
  | "onboarding"
  | "user_added"
  | "user_edited"
  | "correction";

export interface MemoryItem {
  id: Uuid;
  kind: MemoryKind;
  key: string | null;
  statement: string;
  status: MemoryStatus;
  source: MemorySourceKind;
  pinned: boolean;
  confirmations: number;
  first_seen_at: IsoDateTime;
  last_confirmed_at: IsoDateTime | null;
  sensitive_category: string | null;
  /** Sent on the list where it is cheap, so a row can show its quote at once. */
  sources?: MemorySource[];
}

export interface MemorySource {
  id: Uuid;
  message_id: Uuid;
  conversation_id: Uuid;
  conversation_title: string | null;
  seq: number | null;
  quote_text: string;
  quote_start: number | null;
  quote_end: number | null;
  message_created_at: IsoDateTime;
}

export interface UserProfile {
  version: number;
  profile_text: string;
  trigger: string | null;
  created_at: IsoDateTime;
}

export type AssertionKind = "affirm" | "deny" | "amend" | "scope";

export interface UserAssertion {
  id: Uuid;
  kind: AssertionKind;
  statement: string;
  topic: string | null;
  status: "active" | "retracted";
  created_at: IsoDateTime;
}

/* ------------------------------------------------------------- streams */

/** `POST /conversations/{id}/messages` — text/event-stream frames. */
export type ChatStreamEvent =
  | { event: "message.user"; data: { id: Uuid; seq: number } }
  | { event: "delta"; data: { text: string } }
  | { event: "thinking"; data: Record<string, never> }
  | {
      event: "message.assistant";
      data: { id: Uuid; seq: number; status: MessageStatus; usage?: Record<string, number> };
    }
  | { event: "error"; data: { code: string; detail?: string } };

/** `GET /events` — the per-user SSE channel. */
export type UserEvent =
  | { event: "recognition.created"; data: { recognition_id: Uuid; conversation_id: Uuid | null } }
  | { event: "recognition.withdrawn"; data: { recognition_id: Uuid; reason: string } }
  | { event: "correction.effect.ready"; data: { feedback_id: Uuid } }
  | { event: "correction.effect.updated"; data: { feedback_id: Uuid } }
  | { event: "profile.updated"; data: { version: number } }
  | { event: "heartbeat"; data: Record<string, never> };

/* ----------------------------------------------------------------- job */

export interface JobRef {
  job_id: Uuid;
}

export interface JobStatus {
  id: Uuid;
  status: "queued" | "running" | "done" | "failed" | "dead";
  lane: "fast" | "slow";
  attempts: number;
  /** Set when the handler returned something the screen can use. */
  result?: Record<string, unknown> | null;
}

/* --------------------------------------------------------- onboarding */

export interface OnboardingQuestion {
  index: number;
  prompt: string;
  /** A sentence under the question explaining why it is being asked. */
  note?: string | null;
}

export interface OnboardingAnswer {
  index: number;
  text: string;
  created_at: IsoDateTime;
}

/** One thing KnoRI kept from an onboarding answer, with the words it came from. */
export interface OnboardingNote {
  id: Uuid;
  kind: MemoryKind;
  statement: string;
  quote_text: string | null;
}

export interface OnboardingState {
  /** 1 = about you · 2 = consent · 3 = the three questions. */
  step: number;
  complete: boolean;
  questions: OnboardingQuestion[];
  answers: OnboardingAnswer[];
  conversation_id: Uuid | null;
  noted: OnboardingNote[];
}

export interface OnboardingAnswerResult {
  /** What KnoRI says back, so step 3 reads as a conversation and not a form. */
  reply: string | null;
  noted: OnboardingNote[];
  next_step: number | null;
}

/* ------------------------------------------------------ conversations */

/** `POST /conversations` — a conversation plus everything the opener needs. */
export interface ConversationStart {
  conversation: Conversation;
  opener: string | null;
  welcome_back: WelcomeBack | null;
}

/** `GET /conversations/{id}/messages` */
export interface MessagePage {
  messages: Message[];
  events: ConversationEvent[];
  has_more?: boolean;
}

/* ------------------------------------------------------- recognitions */

export interface RecognitionHistoryEntry {
  id: Uuid;
  /** e.g. "created", "presented", "accepted", "corrected", "withdrawn", "revised". */
  event: string;
  /** The event written as a sentence by the API: "You corrected this." */
  label: string;
  actor: "user" | "system";
  at: IsoDateTime;
  payload?: Record<string, unknown>;
}

export interface FeedbackAccepted {
  feedback_id: Uuid;
}

/* -------------------------------------------------------------- memory */

export interface MemoryItemInput {
  kind: MemoryKind;
  statement: string;
}

export interface MemoryItemPatch {
  statement?: string;
  pinned?: boolean;
  status?: MemoryStatus;
}

/* ------------------------------------------------------------ account */

export interface MePatch {
  display_name?: string;
  preferred_name?: string | null;
  timezone?: string;
}

export interface PasswordChange {
  current_password: string;
  new_password: string;
}
