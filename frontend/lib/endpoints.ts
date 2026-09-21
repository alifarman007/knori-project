/**
 * Every `/api/v1` call the web app makes, in one typed list (plan.md §7).
 *
 * Screens import from here and never build a path themselves, so a contract
 * change is a single edit and a type error rather than a silent 404. Nothing in
 * this file takes a user id: the session cookie decides whose rows come back,
 * which is the API's own rule and the reason a cross-user read is a 404.
 *
 * When the backend exports OpenAPI, this file is what gets regenerated.
 */

import { api, unwrapList } from "@/lib/api";
import type {
  Conversation,
  ConversationStart,
  CorrectionEffect,
  FeedbackAccepted,
  FeedbackRequest,
  JobRef,
  JobStatus,
  Me,
  MemoryItem,
  MemoryItemInput,
  MemoryItemPatch,
  MemorySource,
  MePatch,
  MessagePage,
  OnboardingAnswerResult,
  OnboardingState,
  Page,
  PasswordChange,
  Recognition,
  EvidenceRole,
  IsoDateTime,
  ProvenanceItem,
  RecognitionDetail,
  RecognitionHistoryEntry,
  RecognitionSummary,
  UserAssertion,
  UserProfile,
  UserSettings,
  Uuid,
} from "@/lib/types";

/* ---------------------------------------------------------------- auth */

export interface RegisterInput {
  email: string;
  password: string;
  display_name: string;
  invite_code?: string;
}

export const auth = {
  register: (input: RegisterInput) => api.post<void>("/auth/register", input),
  verifyEmail: (token: string) => api.post<void>("/auth/verify-email", { token }),
  resendVerification: (email: string) => api.post<void>("/auth/resend-verification", { email }),
  login: (email: string, password: string) => api.post<void>("/auth/login", { email, password }),
  logout: () => api.post<void>("/auth/logout"),
  logoutAll: () => api.post<void>("/auth/logout-all"),
  forgotPassword: (email: string) => api.post<void>("/auth/password/forgot", { email }),
  resetPassword: (token: string, password: string) =>
    api.post<void>("/auth/password/reset", { token, password }),
};

/* ------------------------------------------------------------------ me */

/**
 * `GET /me` is specified as the user record; some builds nest it under `user`
 * and inline the settings. Reading both shapes costs four lines and removes a
 * whole class of "the app went blank" bug reports.
 */
interface RawMe {
  user?: Me;
  settings?: UserSettings;
}

export interface Session {
  user: Me;
  settings: UserSettings | null;
}

export const me = {
  async load(): Promise<Session> {
    const raw = await api.get<Me & RawMe>("/me");
    const user = raw.user ?? (raw as Me);
    if (raw.settings) return { user, settings: raw.settings };
    const settings = await api.get<UserSettings>("/me/settings").catch(() => null);
    return { user, settings };
  },
  update: (patch: MePatch) => api.patch<Me>("/me", patch),
  settings: () => api.get<UserSettings>("/me/settings"),
  updateSettings: (patch: Partial<UserSettings>) =>
    api.patch<UserSettings>("/me/settings", patch),
  changePassword: (input: PasswordChange) => api.post<void>("/me/password", input),
  acceptLegal: (tos_version: string, privacy_version: string) =>
    api.post<void>("/me/legal/accept", { tos_version, privacy_version }),
  deleteAccount: (password: string) => api.delete<void>("/me", { password }),
  undelete: () => api.post<void>("/me/undelete"),
};

/* ---------------------------------------------------------- onboarding */

export const onboarding = {
  state: () => api.get<OnboardingState>("/onboarding"),
  answer: (step: number, text: string) =>
    api.post<OnboardingAnswerResult>("/onboarding/answer", { step, text }),
  complete: () => api.post<OnboardingState>("/onboarding/complete"),
};

/* -------------------------------------------------------- conversations */

export const conversations = {
  list: (cursor?: string) =>
    api.get<Page<Conversation>>("/conversations", { query: { cursor } }),
  create: (isIncognito = false) =>
    api.post<ConversationStart>("/conversations", { is_incognito: isIncognito }),
  get: (id: Uuid) => api.get<Conversation>(`/conversations/${id}`),
  rename: (id: Uuid, title: string) => api.patch<Conversation>(`/conversations/${id}`, { title }),
  archive: (id: Uuid) => api.patch<Conversation>(`/conversations/${id}`, { archived: true }),
  remove: (id: Uuid) => api.delete<void>(`/conversations/${id}`),
  messages: (id: Uuid, options: { before_seq?: number; around_seq?: number; limit?: number } = {}) =>
    api.get<MessagePage>(`/conversations/${id}/messages`, { query: { ...options } }),
  deleteMessage: (id: Uuid, seq: number) =>
    api.delete<void>(`/conversations/${id}/messages/${seq}`),
};

/** Path for the streaming POST; the body goes through `postStream`. */
export function messagesPath(conversationId: Uuid): string {
  return `/conversations/${conversationId}/messages`;
}

/* -------------------------------------------------------- recognitions */

export const recognitions = {
  /** `tab` is the API's own grouping ("new", "accepted", …) — it maps tabs to states. */
  list: (tab?: string, cursor?: string) =>
    api.get<Page<Recognition>>("/recognitions", { query: { state: tab, cursor } }),
  summary: () => api.get<RecognitionSummary>("/recognitions/summary"),
  get: async (id: Uuid) =>
    adaptDetail(await api.get<ApiRecognitionDetail>(`/recognitions/${id}`)),
  async history(id: Uuid): Promise<RecognitionHistoryEntry[]> {
    return unwrapList<RecognitionHistoryEntry>(await api.get(`/recognitions/${id}/history`));
  },
  markSeen: (id: Uuid) => api.post<void>(`/recognitions/${id}/seen`),
  feedback: (id: Uuid, body: FeedbackRequest) =>
    api.post<FeedbackAccepted>(`/recognitions/${id}/feedback`, body),
  effect: (feedbackId: Uuid) => api.get<CorrectionEffect>(`/corrections/${feedbackId}/effect`),
  run: () => api.post<JobRef>("/recognitions/run"),
};

export const jobs = {
  get: (id: Uuid) => api.get<JobStatus>(`/jobs/${id}`),
};

/* -------------------------------------------------------------- memory */

export const memory = {
  async items(filter: { kind?: string; status?: string } = {}): Promise<MemoryItem[]> {
    return unwrapList<MemoryItem>(await api.get("/memory/items", { query: { ...filter } }));
  },
  add: (input: MemoryItemInput) => api.post<MemoryItem>("/memory/items", input),
  update: (id: Uuid, patch: MemoryItemPatch) => api.patch<MemoryItem>(`/memory/items/${id}`, patch),
  retract: (id: Uuid) => api.delete<void>(`/memory/items/${id}`),
  async sources(id: Uuid): Promise<MemorySource[]> {
    return unwrapList<MemorySource>(await api.get(`/memory/items/${id}/sources`));
  },
  profile: () => api.get<UserProfile>("/memory/profile"),
  async assertions(): Promise<UserAssertion[]> {
    return unwrapList<UserAssertion>(await api.get("/memory/assertions"));
  },
  retractAssertion: (id: Uuid) => api.delete<void>(`/memory/assertions/${id}`),
};

/** The export is a download, not JSON the client parses. */
export const EXPORT_PATH = "/me/export";
export const EVENTS_PATH = "/events";


/* ------------------------------------------------- recognition detail shape */

/**
 * The API groups evidence by role and calls a quote a `quote`; the screens want one
 * ordered list of `ProvenanceItem`. Translating once here keeps that difference out
 * of the components — and means a change on either side has a single place to meet.
 */
interface ApiEvidenceItem {
  id: Uuid;
  kind: "signal" | "assertion";
  role: EvidenceRole;
  weight: number;
  quote: string;
  quote_start: number | null;
  quote_end: number | null;
  scrubbed: boolean;
  message_id: Uuid | null;
  conversation_id: Uuid | null;
  conversation_title: string | null;
  seq: number | null;
  said_at: IsoDateTime | null;
  deep_link: string | null;
  note: string | null;
}

type ApiRecognitionDetail = Omit<RecognitionDetail, "provenance" | "confidence_in_words"> & {
  evidence: {
    supports: ApiEvidenceItem[];
    contradicts: ApiEvidenceItem[];
    context: ApiEvidenceItem[];
  };
};

function adaptDetail(raw: ApiRecognitionDetail): RecognitionDetail {
  const groups = [raw.evidence.supports, raw.evidence.contradicts, raw.evidence.context];
  const provenance: ProvenanceItem[] = groups.flat().map((item, index) => ({
    id: item.id,
    kind: item.kind,
    role: item.role,
    weight: item.weight,
    quote_text: item.quote,
    quote_start: item.quote_start,
    quote_end: item.quote_end,
    message_id: item.message_id,
    conversation_id: item.conversation_id,
    conversation_title: item.conversation_title,
    seq: item.seq,
    message_created_at: item.said_at,
    scrubbed: item.scrubbed,
    note: item.note,
    display_order: index,
    deep_link: item.deep_link,
  }));
  return { ...raw, provenance, confidence_in_words: raw.confidence.plain };
}
