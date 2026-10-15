# ADR-006 — Our own UI primitives, not a third-party component library

**Status:** accepted · **Date:** Phase 1 build · **Source:** `plan.md` §1, §8

## Context

`plan.md` originally named **shadcn/ui** as the component layer, which is what most
Next.js projects reach for. The code does not use it, or Radix, or MUI, or any other
component library: `frontend/components/ui/` holds twenty primitives written in this
repository (plus one hook), styled with Tailwind 4 and a token file.

This ADR records that deviation and why it stands, rather than leaving the plan and
the code disagreeing — a reviewer comparing the two would reasonably ask which is
true.

## Decision

Keep the primitives in the repository. Do not add a component library in Phase 1.

## Why

**The product's look is the product.** KnoRI's whole claim is that it tells you
something about yourself and shows you the evidence. That asks for a quiet, literate
interface — a serif face for what KnoRI claims, a plain face for what the product says
about itself, one accent colour reserved for the moment it has noticed something. A
library's defaults pull in the opposite direction: they make an application look like
every other application built that year, and overriding them far enough to escape that
costs more than writing a button.

**Accessibility is a small, known surface here.** The accessible behaviour we actually
need — focus trapping in the dialog and the bottom sheet, roving focus in the tabs,
labelled fields, visible focus rings, reduced-motion respect — is in twenty small
files we control. That is cheaper to audit than a dependency tree, and it cannot
regress underneath us in a minor release.

**Handover.** Sway owns this code and may hand it to another vendor. Twenty plain
React files with no runtime dependency are readable by anyone who knows React. A
vendored copy of a library that has since moved on is not.

## Cost, honestly

- We write and maintain components somebody else would have given us. A date picker or
  a combobox, neither of which Phase 1 needs, would be real work.
- No upstream accessibility fixes arrive for free; ours are as good as our own tests.
- A developer who knows shadcn/ui cannot apply that knowledge directly. This matters
  for the client's own UI/UX developer, so `docs/client-review/06-DESIGN-SYSTEM-REFERENCE.md`
  documents every token, component and prop for exactly that reader.

## When to revisit

If Phase 2 or later needs a complex widget — a full data grid, a rich text editor, a
date range picker — take the single dependency for that widget rather than adopting a
whole library and restyling it. The primitives here are not an argument against ever
using somebody else's code; they are an argument against buying a visual identity we
would then have to undo.
