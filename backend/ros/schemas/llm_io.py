"""What we ask models to return, and what we accept back.

Rules that apply to every schema here (CLAUDE.md → LLM API rules):

* no numeric or length constraints on the wire — the API strips them, and one
  out-of-range field would otherwise throw away a whole batch. We clamp in code
  (``ros.engine.validate``) and count what we dropped;
* every optional field is nullable, no unions of objects, ``additionalProperties``
  false — so the same schema works on Anthropic and on OpenAI;
* models refer to signals and interpretations by short ids ("S12", "I3"), never
  UUIDs: shorter, cheaper, and a hallucinated id cannot match anything real.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ------------------------------------------------------------------ extraction (Sonnet)


class ExtractedSignal(Strict):
    message_ref: str = Field(description="Short id of the message this came from, e.g. 'M2'.")
    kind: str = Field(
        description="statement|behavior|preference|value|goal|emotion|situation|reflection"
    )
    subject: str = Field(description="self|other|hypothetical|unclear — who the sentence is about.")
    topic: str = Field(description="Topic key from the supplied list, e.g. 'work.decisions'.")
    content: str = Field(
        description="One neutral third-person sentence describing the observation."
    )
    quote_text: str = Field(description="The user's exact words, copied character for character.")
    polarity: int = Field(description="-1 negative, 0 neutral, 1 positive.")
    strength: float = Field(description="1.0 explicit, 0.6 implied, 0.3 weak or hypothetical.")
    sensitive_category: str | None = Field(
        default=None, description="One of the sensitive categories, or null."
    )
    context_tags: list[str] = Field(
        default_factory=list, description="Situation tags, e.g. 'work'."
    )


class ExtractedMemory(Strict):
    message_ref: str
    kind: str = Field(description="fact|preference|goal|event|routine|constraint|relationship")
    key: str | None = Field(default=None, description="Stable key like 'fact.diet', or null.")
    statement: str = Field(description="What the user told KnoRI, in the third person.")
    quote_text: str
    sensitive_category: str | None = None


class SignalExtraction(Strict):
    signals: list[ExtractedSignal] = Field(default_factory=list)
    memory_candidates: list[ExtractedMemory] = Field(default_factory=list)
    skipped_reason: str | None = None


# --------------------------------------------------------------- interpretation (Opus)


class ProposedEvidence(Strict):
    signal_ref: str = Field(description="Short id of a signal given in the input, e.g. 'S7'.")
    role: str = Field(description="supports|contradicts|context")
    weight: float = Field(description="0-1: how strongly this signal bears on the claim.")
    note: str = Field(description="One line: why this signal matters for this claim.")


class Proposal(Strict):
    action: str = Field(description="create|attach|revise|retire")
    ref: str | None = Field(
        default=None, description="Existing interpretation id for attach/revise/retire."
    )
    kind: str = Field(description="pattern|preference|value|tension")
    topic: str
    statement: str = Field(description="The claim, third person, neutral, no diagnosis.")
    rationale: str
    evidence: list[ProposedEvidence] = Field(default_factory=list)
    model_confidence: float = Field(description="0-1: your own confidence in this claim.")
    sensitive_category: str | None = None


class Declined(Strict):
    about: str = Field(description="What you considered saying.")
    reason: str = Field(
        description=(
            "single_occurrence|ambiguous|contradicted|user_denied|sensitive|trivial|"
            "already_known|not_self"
        )
    )
    signal_refs: list[str] = Field(default_factory=list)


class InterpretationBatch(Strict):
    proposals: list[Proposal] = Field(default_factory=list)
    declined: list[Declined] = Field(default_factory=list)


# ----------------------------------------------------------------- composition (Opus)


class RecognitionDraft(Strict):
    title: str = Field(description="Up to 8 words, sentence case, no full stop.")
    body: str = Field(
        description="Two or three sentences, second person, paraphrased — never quote."
    )
    explanation: str = Field(description="Plain words: why KnoRI thinks this, and how sure it is.")
    cited_signal_refs: list[str] = Field(default_factory=list)


# ------------------------------------------------------------------ correction (Opus)


class CorrectionParse(Strict):
    kind: str = Field(description="deny|amend|scope")
    assertion_statement: str = Field(
        description="The user's claim, third person, bare, no wrapper."
    )
    replacement_claim: str | None = Field(
        default=None, description="For amend: the corrected version of the claim."
    )
    contradicted_signal_refs: list[str] = Field(default_factory=list)
    topic: str | None = None


class SameClaim(Strict):
    same: bool
    why: str


# --------------------------------------------------------------- background (Sonnet)


class ConversationSummary(Strict):
    summary: str = Field(description="What was discussed, in a short paragraph.")
    open_threads: list[str] = Field(default_factory=list)
    tone: str | None = None


class ProfileSection(Strict):
    heading: str
    lines: list[str] = Field(default_factory=list)


class ProfileBuild(Strict):
    profile_text: str = Field(
        description="Markdown, under 900 tokens, written to be read by the user."
    )
    sections: list[ProfileSection] = Field(default_factory=list)


class OnboardingParse(Strict):
    preferred_name: str | None = None
    chat_style: str | None = Field(default=None, description="warm|direct")
    memories: list[ExtractedMemory] = Field(default_factory=list)
    do_not_notice: list[str] = Field(
        default_factory=list, description="Topics the user asked KnoRI to leave alone."
    )


class ChatTitle(Strict):
    title: str = Field(description="Up to 6 words describing the conversation.")
