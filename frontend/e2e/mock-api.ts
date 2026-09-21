import type { Page, Route } from "@playwright/test";

/**
 * A stand-in for `/api/v1`, served from the browser.
 *
 * The e2e specs are about the product's behaviour — does a correction reach the
 * "what changed" panel, does a deep link mark the right characters — and those
 * answers must not depend on a running FastAPI, a database or an API key. The
 * shapes here follow plan.md §7 and `lib/types.ts`; when the real API drifts,
 * this file is the one place that has to move with it.
 */

const NOW = Date.now();

function iso(minutesAgo: number): string {
  return new Date(NOW - minutesAgo * 60_000).toISOString();
}

interface StoredMessage {
  id: string;
  seq: number;
  role: "user" | "assistant";
  content: string;
  status: string;
  created_at: string;
}

export interface MockState {
  onboardingComplete: boolean;
  answers: { index: number; text: string }[];
  feedback: { action: string; correction_text?: string; reason_code?: string } | null;
  messagesSent: string[];
  /** Turns added during the test, so a reload shows them like the real API would. */
  added: StoredMessage[];
  legalAccepted: boolean;
}

const REPLY = "That tracks with what you said on Tuesday.";

const QUOTE_ONE = "I don't know what I think until I've written it out properly";
const QUOTE_TWO = "spent the whole morning on the doc and the answer got obvious";

const CONVERSATION_ID = "11111111-1111-4111-8111-111111111111";
const RECOGNITION_ID = "22222222-2222-4222-8222-222222222222";
const FEEDBACK_ID = "33333333-3333-4333-8333-333333333333";

function messages() {
  return [
    {
      id: "m1",
      seq: 1,
      role: "user",
      content: QUOTE_ONE,
      status: "complete",
      created_at: iso(60 * 40),
    },
    {
      id: "m2",
      seq: 2,
      role: "assistant",
      content: "That sounds like writing is part of how you decide, not a record of it.",
      status: "complete",
      created_at: iso(60 * 40 - 1),
    },
    {
      id: "m3",
      seq: 3,
      role: "user",
      content: QUOTE_TWO,
      status: "complete",
      created_at: iso(30),
    },
  ];
}

function provenance() {
  return [
    {
      id: "p1",
      kind: "signal",
      role: "supports",
      weight: 1,
      quote_text: QUOTE_ONE,
      quote_start: 0,
      quote_end: QUOTE_ONE.length,
      message_id: "m1",
      conversation_id: CONVERSATION_ID,
      conversation_title: "Deciding about the move",
      seq: 1,
      message_created_at: iso(60 * 40),
      scrubbed: false,
      note: null,
      display_order: 0,
    },
    {
      id: "p2",
      kind: "signal",
      role: "supports",
      weight: 1,
      quote_text: QUOTE_TWO,
      quote_start: 0,
      quote_end: QUOTE_TWO.length,
      message_id: "m3",
      conversation_id: CONVERSATION_ID,
      conversation_title: "Thursday",
      seq: 3,
      message_created_at: iso(30),
      scrubbed: false,
      note: null,
      display_order: 1,
    },
    {
      id: "p3",
      kind: "signal",
      role: "contradicts",
      weight: 0.4,
      quote_text: "sometimes I just call it and move on",
      quote_start: 0,
      quote_end: 34,
      message_id: "m4",
      conversation_id: CONVERSATION_ID,
      conversation_title: "Thursday",
      seq: 5,
      message_created_at: iso(25),
      scrubbed: false,
      note: null,
      display_order: 2,
    },
  ];
}

function recognition(state: MockState) {
  const answered = state.feedback !== null;
  return {
    id: RECOGNITION_ID,
    kind: "pattern",
    title: "You work things out on the page",
    body: "Writing looks like how you reach a decision rather than how you record one. Twice you described a choice settling only once it was written down in full.",
    confidence: 0.73,
    confidence_label: "likely",
    state: answered ? "corrected" : "presented",
    supersedes_id: null,
    created_at: iso(20),
    presented_at: iso(20),
    resolved_at: answered ? iso(1) : null,
    seen_at: null,
    evidence_count: 2,
    evidence_day_count: 2,
  };
}

function detail(state: MockState) {
  return {
    ...recognition(state),
    explanation:
      "Two things you said across two days point the same way, and one thing pulls against it. KnoRI is showing this as a first impression, not a conclusion.",
    confidence_in_words:
      "Enough of what you said points this way to be worth showing you — but it is a first impression, not a conclusion.",
    interpretation: {
      id: "44444444-4444-4444-8444-444444444444",
      version: 1,
      kind: "pattern",
      topic: "work_habits",
      statement: "The user reaches decisions by writing them out in full.",
    },
    provenance: provenance(),
    feedback: state.feedback
      ? {
          id: FEEDBACK_ID,
          action: state.feedback.action,
          correction_text: state.feedback.correction_text ?? null,
          reason_code: state.feedback.reason_code ?? null,
          created_at: iso(1),
          processed_at: iso(0),
        }
      : null,
    correction_effect: null,
  };
}

function json(route: Route, body: unknown, status = 200) {
  return route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

function frame(event: string, data: unknown): string {
  return `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
}

/** Install the mock. Call before `page.goto`. */
export async function installApiMock(
  page: Page,
  overrides: Partial<MockState> = {},
): Promise<MockState> {
  const state: MockState = {
    onboardingComplete: false,
    answers: [],
    feedback: null,
    messagesSent: [],
    added: [],
    legalAccepted: false,
    ...overrides,
  };

  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.replace(/^.*\/api\/v1/, "");
    const method = request.method();

    /* ---------------------------------------------------------- account */
    if (path === "/me" && method === "GET") {
      return json(route, {
        id: "55555555-5555-4555-8555-555555555555",
        email: "you@example.com",
        display_name: "Alif",
        preferred_name: null,
        timezone: "Asia/Dhaka",
        role: "user",
        email_verified: true,
        onboarding_complete: state.onboardingComplete,
        created_at: iso(60 * 24 * 3),
      });
    }
    if (path === "/me" && method === "PATCH") {
      const body = request.postDataJSON() as Record<string, string>;
      return json(route, {
        id: "55555555-5555-4555-8555-555555555555",
        email: "you@example.com",
        display_name: body.display_name ?? "Alif",
        preferred_name: body.preferred_name ?? null,
        timezone: body.timezone ?? "Asia/Dhaka",
        role: "user",
        email_verified: true,
        onboarding_complete: state.onboardingComplete,
        created_at: iso(60 * 24 * 3),
      });
    }
    if (path === "/me/settings") {
      return json(route, {
        recognition_enabled: true,
        memory_enabled: true,
        max_recognitions_per_day: 2,
        chat_style: "warm",
      });
    }
    if (path === "/me/legal/accept") {
      state.legalAccepted = true;
      return json(route, {});
    }

    /* ------------------------------------------------------- onboarding */
    if (path === "/onboarding" && method === "GET") {
      return json(route, {
        step: state.answers.length > 0 ? 3 : 1,
        complete: state.onboardingComplete,
        questions: [],
        answers: state.answers.map((answer) => ({ ...answer, created_at: iso(1) })),
        conversation_id: CONVERSATION_ID,
        noted: [],
      });
    }
    if (path === "/onboarding/answer") {
      const body = request.postDataJSON() as { step: number; text: string };
      state.answers.push({ index: body.step, text: body.text });
      return json(route, {
        reply: "Noted. Thank you.",
        noted: [
          {
            id: `n${body.step}`,
            kind: body.step === 3 ? "preference" : "fact",
            statement: `Something KnoRI kept from answer ${body.step}.`,
            quote_text: body.text.slice(0, 40),
          },
        ],
        next_step: body.step + 1,
      });
    }
    if (path === "/onboarding/complete") {
      state.onboardingComplete = true;
      return json(route, { step: 3, complete: true, questions: [], answers: [], noted: [] });
    }

    /* ----------------------------------------------------- conversations */
    if (path === "/conversations" && method === "GET") {
      return json(route, {
        items: [
          {
            id: CONVERSATION_ID,
            kind: "chat",
            title: "Thursday",
            is_incognito: false,
            message_count: 3,
            last_message_at: iso(30),
            archived_at: null,
            created_at: iso(60 * 40),
          },
        ],
        next_cursor: null,
      });
    }
    if (path === `/conversations/${CONVERSATION_ID}/messages` && method === "GET") {
      return json(route, {
        messages: [...messages(), ...state.added],
        events: [
          {
            id: "e1",
            kind: "recognition",
            after_seq: 3,
            recognition_id: RECOGNITION_ID,
          },
        ],
      });
    }
    if (path.endsWith("/messages") && method === "POST") {
      const body = request.postDataJSON() as { content: string };
      state.messagesSent.push(body.content);
      const base = 9 + state.added.length;
      state.added.push(
        {
          id: `u${base}`,
          seq: base,
          role: "user",
          content: body.content,
          status: "complete",
          created_at: iso(0),
        },
        {
          id: `a${base + 1}`,
          seq: base + 1,
          role: "assistant",
          content: REPLY,
          status: "complete",
          created_at: iso(0),
        },
      );
      return route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body:
          frame("message.user", { id: `u${base}`, seq: base }) +
          frame("thinking", {}) +
          frame("delta", { text: REPLY.slice(0, 17) }) +
          frame("delta", { text: REPLY.slice(17) }) +
          frame("message.assistant", { id: `a${base + 1}`, seq: base + 1, status: "complete" }),
      });
    }

    /* ------------------------------------------------------ recognitions */
    if (path === "/recognitions/summary") {
      return json(route, {
        new: state.feedback ? 0 : 1,
        accepted: 0,
        corrected: state.feedback ? 1 : 0,
        rejected: 0,
        dismissed: 0,
        unread: state.feedback ? 0 : 1,
      });
    }
    if (path === "/recognitions" && method === "GET") {
      const wanted = (url.searchParams.get("state") ?? "").split(",");
      const card = recognition(state);
      return json(route, {
        items: wanted.includes(card.state) ? [card] : [],
        next_cursor: null,
      });
    }
    if (path === `/recognitions/${RECOGNITION_ID}/history`) {
      return json(route, {
        items: [
          { id: "h1", event: "created", actor: "system", created_at: iso(20), detail: null },
          { id: "h2", event: "presented", actor: "system", created_at: iso(20), detail: null },
        ],
      });
    }
    if (path === `/recognitions/${RECOGNITION_ID}/seen`) return json(route, {});
    if (path === `/recognitions/${RECOGNITION_ID}/feedback`) {
      state.feedback = request.postDataJSON() as MockState["feedback"];
      return json(route, { feedback_id: FEEDBACK_ID }, 202);
    }
    if (path === `/recognitions/${RECOGNITION_ID}`) return json(route, detail(state));
    if (path === "/recognitions/run") return json(route, { job_id: "job-1" });
    if (path === "/jobs/job-1") {
      return json(route, { id: "job-1", status: "done", lane: "slow", attempts: 1, result: {} });
    }

    if (path === `/corrections/${FEEDBACK_ID}/effect`) {
      return json(route, {
        feedback_id: FEEDBACK_ID,
        status: "ready",
        summary: "KnoRI dropped the claim that you avoid deciding, and kept your version instead.",
        effects: [],
        recognitions_withdrawn: [RECOGNITION_ID],
        recognitions_created: [],
        assertions_created: ["a1"],
        profile_before_text: "Reaches decisions slowly, by writing.",
        profile_after_text: "Decides quickly, then writes the decision up.",
      });
    }

    /* ------------------------------------------------------------ memory */
    if (path === "/memory/assertions") {
      return json(route, {
        items: state.feedback
          ? [
              {
                id: "a1",
                kind: "amend",
                statement: "The user decides quickly and writes the decision up afterwards.",
                topic: "work_habits",
                status: "active",
                created_at: iso(1),
              },
            ]
          : [],
        next_cursor: null,
      });
    }
    if (path === "/memory/items") {
      return json(route, { items: [], next_cursor: null });
    }
    if (path === "/memory/profile") {
      return json(route, {
        version: 2,
        profile_text: "Writes to think. Prefers the blunt version.",
        trigger: "correction",
        created_at: iso(5),
      });
    }

    /* ------------------------------------------------------------ events */
    if (path === "/events") {
      // One heartbeat, then the stream ends; the hook reconnects on its own.
      return route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: frame("heartbeat", {}),
      });
    }

    /* -------------------------------------------------------------- auth */
    if (path.startsWith("/auth/")) return json(route, {});

    return json(route, { title: "Not found in the mock", status: 404 }, 404);
  });

  return state;
}

export const MOCK = { CONVERSATION_ID, RECOGNITION_ID, QUOTE_ONE, QUOTE_TWO };
