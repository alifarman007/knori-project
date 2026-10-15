# Design system reference

The visual contract for the KnoRI web app. Every token name, class name, prop
and state below was read out of the source files, not from a style guide
written beside them. Where a number is an accessibility claim I have measured
it and given the figure.

Two files own everything:

| File | Role |
|---|---|
| `frontend/app/tokens.css` | the values — colour, type stacks, radius, elevation, grain — for light and dark |
| `frontend/app/globals.css` | maps them to Tailwind utilities (`@theme inline`), plus the base layer, keyframes and six helper classes |

No component holds a colour, a radius or a shadow of its own. Change a value in
`tokens.css` and all 20 primitives, all 18 pages and both themes follow.

---

## 1. The idea the tokens serve

The design name in the file header is **"quiet archive"**. The product's job is
to make a person feel accurately understood, so the surface reads like a
well-kept notebook rather than a dashboard: warm paper, ink, hairline rules, and
exactly **one** accent — ochre — reserved for Recognition moments and never used
as decoration.

That last constraint is the one that does the work. If the accent appears on a
Save button, it stops meaning anything when it appears on a card.

---

## 2. Colour

Every token is a CSS custom property named `--knori-*` in `tokens.css`, exposed
as a Tailwind colour in `globals.css`. The Tailwind name is what you write:
`bg-paper`, `text-ink-muted`, `border-line-strong`.

### Surfaces

| Tailwind | Token | Light | Dark | For |
|---|---|---|---|---|
| `paper` | `--knori-bg` | `#faf8f3` | `#131210` | the page itself |
| `sunken` | `--knori-bg-sunken` | `#f2eee4` | `#0d0c0a` | wells, code, quiet strips, card footers |
| `surface` | `--knori-surface` | `#ffffff` | `#1b1916` | cards |
| `raised` | `--knori-surface-raised` | `#fffefb` | `#221f1b` | dialogs, sheets, popovers, toasts |
| `overlay` | `--knori-overlay` | `rgb(30 26 20 / 0.34)` | `rgb(8 7 6 / 0.62)` | the scrim behind a modal |

Three levels, not five. A card sits on paper; a dialog sits above the card. If a
design needs a fourth level, it probably needs fewer layers.

### Ink

| Tailwind | Token | Light | Dark | For |
|---|---|---|---|---|
| `ink` | `--knori-ink` | `#191714` | `#f0eae0` | primary text, headings |
| `ink-secondary` | `--knori-ink-secondary` | `#4b453d` | `#c6bdb0` | body copy at rest |
| `ink-muted` | `--knori-ink-muted` | `#756c61` | `#968d80` | labels, metadata, counts |
| `ink-inverted` | `--knori-ink-inverted` | `#faf8f3` | `#16140f` | text on an ink-filled button |

### Lines

| Tailwind | Token | Light | Dark | For |
|---|---|---|---|---|
| `line` | `--knori-line` | `#e5ddd0` | `#302c26` | hairline dividers, card borders |
| `line-strong` | `--knori-line-strong` | `#cec3b0` | `#453e35` | input borders, scrollbar thumb, grab handles |

`globals.css` sets `border-color: var(--knori-line)` on `*`, `*::before` and
`*::after`, so a bare `border` or `border-t` is already the right colour. You
only name a border colour when you want `line-strong` or a state colour.

### Accent — Recognition only

| Tailwind | Token | Light | Dark | For |
|---|---|---|---|---|
| `accent` | `--knori-accent` | `#955611` | `#e0a458` | the Recognition mark, the card's left edge, the active tab underline |
| `accent-hover` | `--knori-accent-hover` | `#7d4809` | `#edb670` | hover on an accent control |
| `accent-ink` | `--knori-accent-ink` | `#fffdf8` | `#1e1509` | text on an accent fill |
| `accent-soft` | `--knori-accent-soft` | `#f6e9d5` | `#2b2317` | tinted fills, the deep-link highlight, text selection |
| `accent-line` | `--knori-accent-line` | `#e0c69d` | `#55442a` | the rule beside an evidence quote |

Where the accent is allowed to appear, in full:

* the rule under the wordmark (`components/wordmark.tsx`);
* the left edge of a Recognition card (`Card tone="recognition"`);
* the confidence badge when it reads `strong`;
* the underline on the selected tab, and the active item marker in the left rail;
* the rule beside an evidence quote, and the quotation marks themselves;
* the highlighted span a deep link lands on (`bg-accent-soft` in
  `components/chat/message-row.tsx`);
* the "After" column of the correction effect panel;
* the unread count badge and the `on` state of a Switch.

Note what is **not** on that list: the primary button. `Button variant="primary"`
is filled with `ink`, with the comment "the accent belongs to Recognition
moments alone". `variant="accent"` exists for the rare case where an action *is*
a Recognition moment.

### States

| Tailwind | Token | Light | Dark | For |
|---|---|---|---|---|
| `positive` | `--knori-positive` | `#2c6442` | `#7bbb93` | accepted, confirmed |
| `positive-soft` | `--knori-positive-soft` | `#e3eee6` | `#1a2620` | the fill behind it |
| `danger` | `--knori-danger` | `#9c2b22` | `#e78d83` | destructive actions, field errors, contradicting evidence |
| `danger-hover` | `--knori-danger-hover` | `#82211a` | `#f0a49b` | hover on a danger button |
| `danger-soft` | `--knori-danger-soft` | `#f8e5e3` | `#2c1b18` | the fill behind it |
| `danger-ink` | `--knori-danger-ink` | `#fffdfc` | `#24100d` | text on a danger fill |
| `info` | `--knori-info` | `#2a5570` | `#8fb9d4` | neutral notices |
| `info-soft` | `--knori-info-soft` | `#e4ecf2` | `#16222b` | the fill behind it |

### Focus

| Tailwind | Token | Light | Dark |
|---|---|---|---|
| `focus` | `--knori-focus` | `#1d4f6b` | `#8fc4e3` |

A separate hue from both the accent and the state colours, so a focus ring is
never mistaken for a selected state.

### Measured contrast

Computed from the hex values above with the WCAG 2.x relative-luminance
formula. AA for normal text is 4.5:1; AA for text at 18.66px bold or 24px
regular, and for UI component boundaries, is 3:1.

| Pair | Light | Dark |
|---|---|---|
| `ink` on `paper` | 16.85 | 15.65 |
| `ink` on `surface` | 17.89 | 14.66 |
| `ink-secondary` on `paper` | 8.92 | 10.08 |
| `ink-muted` on `paper` | 4.86 | 5.72 |
| `ink-muted` on `surface` | 5.15 | 5.36 |
| `accent` on `paper` | 5.47 | 8.58 |
| `accent` on `accent-soft` | 4.85 | 7.10 |
| `accent-ink` on `accent` | 5.71 | 8.25 |
| `positive` on `paper` | 6.58 | 8.35 |
| `danger` on `paper` | 7.11 | 7.61 |
| `danger-ink` on `danger` | 7.44 | 7.39 |
| `info` on `paper` | 7.52 | 8.97 |
| `focus` on `paper` | 8.30 | 9.96 |

Every text pair above passes AA in both themes. Two caveats, stated plainly:

1. **`ink-muted` on a fully opaque `sunken` is 4.45:1 in light mode** — a 1%
   shortfall against 4.5:1. In the codebase that combination occurs in exactly
   two places: the count badge on an *unselected* tab
   (`components/ui/tabs.tsx`), and the text of a *disabled* input
   (`components/ui/input.tsx`). Disabled controls are exempt from the contrast
   minimum. The tab badge is worth nudging — darkening `--knori-ink-muted` by a
   few points, or putting the badge on `surface`, fixes it. Where `sunken` is
   used at partial opacity (`bg-sunken/50`, `/60`, `/70` — card footers, empty
   states) the blended result is 4.61–4.65:1 and passes.
2. `line-strong` on `paper` is 1.64:1 (light) and 1.78:1 (dark). That is correct
   for a decorative hairline but **below the 3:1 needed for a boundary that is
   the only indication of a control.** Inputs rely on it, which is why they also
   carry an inset shadow and a hover state; do not remove those if you restyle
   the inputs.

---

## 3. Type

### The three faces, and why there are three

Loaded through `next/font/google` in `frontend/app/layout.tsx`, which is what
supplies the `--font-*` variables the token stacks reference.

| Role | Face | Weights | Tailwind | Carries |
|---|---|---|---|---|
| serif | **Newsreader** | 300, 400, 500, 600 + italic | `font-serif` | everything KnoRI says **about the person** |
| sans | **Instrument Sans** | variable | `font-sans` (the body default) | everything the product says **about itself** |
| mono | **IBM Plex Mono** | 400, 500, 600 | `font-mono` | dates, counts, kind tags, eyebrow labels |

The split is the design, not a flourish. A Recognition title, a card body, an
evidence quote, a profile paragraph and a correction being echoed back are all
serif. Buttons, labels, counts, nav, empty-state descriptions and error text are
all sans. **A Recognition should read like a sentence somebody wrote about you,
not like a notification.** If you set a card body in the sans, the product loses
the only cue that tells a person which voice is speaking.

`globals.css` sets `h1, h2, h3, h4` to the serif at weight 400 with
`letter-spacing: -0.015em` and `text-wrap: balance`. A heading does not need a
`font-serif` class; a non-heading that should be serif does.

### The scale

Tokens in the `@theme inline` block of `globals.css`. 4px base, roughly a 1.2
ratio. UI text is 15px and prose is 17px — the two sizes you will use most.

| Tailwind | rem | px | line-height | Used for |
|---|---|---|---|---|
| `text-2xs` | 0.6875 | 11 | 1.45, +0.06em tracking | eyebrow labels, mono tags, count badges |
| `text-xs` | 0.75 | 12 | 1.5 | badge text, "optional" markers |
| `text-sm` | 0.8125 | 13 | 1.55 | metadata, hints, field errors, small buttons |
| `text-base` | 0.9375 | **15** | 1.6 | **the body default** — all UI text |
| `text-md` | 1.0625 | **17** | 1.65 | **prose and everything in the serif** |
| `text-lg` | 1.25 | 20 | 1.5 | card titles, section headings |
| `text-xl` | 1.5 | 24 | 1.35 | Recognition titles, dialog titles |
| `text-2xl` | 1.875 | 30 | 1.25 | page headings |
| `text-3xl` | 2.375 | 38 | 1.15 | 404 and error-page headings |
| `text-4xl` | 3 | 48 | 1.08 | marketing |
| `text-5xl` | 3.75 | 60 | 1.03 | marketing hero |
| `text-6xl` | 4.5 | 72 | 1.00 | marketing hero, large screens |

`text-md` does not exist in stock Tailwind. It is ours, and it is the prose size.

`body` is set to `font-sans`, `text-base`, line-height 1.6, with
`font-feature-settings: "kern", "liga", "calt"` and antialiasing on.

### Six helper classes

In the `@layer components` and `@layer utilities` blocks of `globals.css`. Use
them rather than re-deriving the same stack of utilities.

| Class | What it is |
|---|---|
| `.knori-gutter` | the page gutter: 16px, 32px from 640px, 48px from 1024px |
| `.knori-eyebrow` | mono, `text-2xs`, uppercase, 0.14em tracking, `ink-muted` — section labels and dates |
| `.knori-prose` | serif, `text-md`, line-height 1.72, `ink-secondary`, with `p + p` spacing |
| `.knori-mark` | the accent rule under a heading, as an `::after` |
| `.knori-ruled` | hairline ruled paper, 2rem rhythm, behind the landing hero |
| `.knori-stack` | `> * + * { margin-top: var(--knori-stack-gap, 1rem) }` |

---

## 4. Spacing, radius, elevation

### Spacing

Tailwind's default 4px scale, unchanged. `gap-2` is 8px, `px-5` is 20px. The
conventions actually used, so your work matches what is there:

| Context | Pattern |
|---|---|
| page gutter | `.knori-gutter` — never a hand-written `px-4 sm:px-8` |
| card padding | `px-5 py-5` on phones, `sm:px-6 sm:py-6` from 640px |
| card footer | `px-5 py-4 sm:px-6`, with `border-t border-line` |
| control gap | `gap-2` between buttons, `gap-1.5` inside a label row |
| field stack | `gap-1.5` between label, control and hint |
| section stack | `gap-4` inside a card, `gap-8` between evidence groups |
| reading column | `max-w-3xl` for chat and content, `max-w-prose` for paragraphs |

Breakpoints are Tailwind defaults: `sm` 640, `md` 768, `lg` 1024. Two matter
structurally — the app shell switches from bottom tab bar to left rail at `md`
(768px), and the Sheet goes from bottom sheet to side panel at `sm` (640px).
**Everything is expected to work from 360px wide with no horizontal scroll**;
`body` carries `overflow-x: hidden` as a backstop, not as a licence.

### Radius

| Tailwind | Token | Value | For |
|---|---|---|---|
| `rounded-sm` | `--knori-radius-sm` | 6px | small buttons, icon buttons, chips, skeletons |
| `rounded-md` | `--knori-radius-md` | 10px | inputs, medium and large buttons, alerts, toasts |
| `rounded-lg` | `--knori-radius-lg` | 16px | cards, dialogs, empty states |
| `rounded-xl` | `--knori-radius-xl` | 24px | the sheet's leading edge |

`rounded-full` is used for pills (Badge), the switch track and thumb, and the
scrollbar thumb.

### Elevation

Three shadows, each two layers — a tight contact shadow plus a wide soft one.

| Tailwind | Token | For |
|---|---|---|
| `shadow-soft` | `--knori-shadow-1` | cards at rest, buttons, the segmented control's selected item |
| `shadow-lift` | `--knori-shadow-2` | a Recognition card — the one card that sits slightly above the page |
| `shadow-float` | `--knori-shadow-3` | dialogs, sheets, toasts, tooltips |

In dark mode the same three tokens are redefined with heavier, blacker values,
because a light-mode shadow is invisible on a dark surface. Elevation in dark
mode is carried by the shadow **and** by the `surface` → `raised` step.

### The paper grain

`body::before`, in the base layer: a fixed, `pointer-events: none` layer with an
inline SVG `feTurbulence` fractal noise texture, 180×180, tiled.

* light: `opacity 0.4`, `mix-blend-mode: multiply`
* dark: `opacity 0.22`, `mix-blend-mode: overlay`

It is what makes the surface read as paper rather than as white. Both values are
tokens (`--knori-grain-opacity`, `--knori-grain-blend`), so it can be tuned or
turned off (`opacity: 0`) without touching markup. It sits at `z-index: 0`, and
the app shell and page wrappers use `relative z-10` to sit above it — if you add
a new top-level wrapper, give it `relative z-10` or it will render under the
grain.

---

## 5. Light and dark

Both are first-class. Neither is a filter over the other: every colour token is
written twice.

How the choice is made:

1. **No choice stored** → `@media (prefers-color-scheme: dark)` decides. The
   block is guarded by `:root:not([data-theme="light"])`, so an explicit light
   choice wins over a dark system setting.
2. **A choice stored** → `data-theme="dark"` or `"light"` on `<html>` wins. The
   `:root[data-theme="dark"]` block repeats the dark palette for this case.
3. **Before first paint** → the inline script in `<head>`
   (`themeScript` in `components/theme.tsx`) reads `localStorage["knori-theme"]`
   and sets the attribute, so the page never flashes the wrong palette.
4. **At runtime** → `ThemeProvider` holds `"light" | "dark" | "system"`,
   `ThemeToggle` flips between light and dark, and `useTheme().resolved` tells
   you what is actually on screen. Choosing `system` removes both the attribute
   and the stored key.

Tailwind's `dark:` variant is redefined in `globals.css` with
`@custom-variant dark` to follow exactly the same rule, so `dark:` utilities and
the tokens can never disagree.

The browser chrome colour is set in `app/layout.tsx` → `viewport.themeColor`:
`#faf8f3` light, `#131210` dark. If you change `--knori-bg`, change those too —
they are literal hex values and will not follow.

**When you add a colour, add it in three places**: `:root`, the
`prefers-color-scheme` block, and the `[data-theme="dark"]` block. Then map it in
`@theme inline`. Missing the third is the usual bug, and it only shows up for
someone who has pressed the toggle.

Also themed: text selection (`::selection` uses `accent-soft`), placeholders
(`ink-muted` at full opacity), `hr`, and the scrollbars — 10px, thumb
`line-strong`, `ink-muted` on hover, transparent track, in a
`@supports selector(::-webkit-scrollbar)` block.

---

## 6. Focus and motion

### Focus

One global rule in the base layer:

```css
:focus-visible {
  outline: 2px solid var(--knori-focus);
  outline-offset: 2px;
  border-radius: 3px;
}
```

and immediately after it, a rule that removes the browser default for
`:focus:not(:focus-visible)` on buttons, links, inputs and textareas, so rings
never double up.

Components additionally carry
`focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus`
so the ring survives any element that resets `outline`. That repetition is
deliberate, not leftover.

Offsets vary where the ring would otherwise be clipped: `-2px` inside a tab (the
ring is drawn inward, over the tab's own bottom border), `4px` on a tab panel and
the wordmark, `1px` on an input.

**Rules for anything you add**

* Every interactive element gets a visible ring. Removing `outline` without
  replacing it is the single change most likely to be sent back.
* A focus ring is never the only indication of state. Selected tabs also carry
  an accent underline and a font-weight change; a checked switch also moves its
  thumb and changes its track colour.
* The skip link (`app/layout.tsx`) is `sr-only` until focused, then fixed at
  top-left above everything. It targets `#main` — if you restructure a layout,
  keep an element with `id="main"`.

### Motion

Four named animations, one shared easing, all tokens in `globals.css`.

| Tailwind | Keyframes | Duration | Used by |
|---|---|---|---|
| `animate-rise` | `rise` — 10px up + fade | 0.42s | dialogs, toasts, cards arriving |
| `animate-fade` | `fade` — opacity | 0.24s | scrims, disclosures, tooltips |
| `animate-mark` | `mark` — `scaleX` from the left | 0.5s | the accent rule sweeping in under a heading |
| `animate-spin-quiet` | `spin` | 0.7s linear, infinite | the spinner |

Plus three sheet transforms (`sheet-up`, `sheet-right`, `sheet-left`, 0.3s) and
`sweep` (1.6s, infinite) for the skeleton shimmer. The shared easing is
`--ease-out-quiet: cubic-bezier(0.22, 0.61, 0.36, 1)`.

State transitions are 150ms for colour and border, 200ms for the switch.

**Reduced motion.** One block at the end of `globals.css` sets
`animation-duration: 0.01ms`, `animation-iteration-count: 1`,
`transition-duration: 0.01ms` and `scroll-behavior: auto` on everything under
`prefers-reduced-motion: reduce`. Two consequences:

* CSS animation is handled for you. You do not need a per-component check.
* The sheet and the skeleton shimmer use `motion-safe:` prefixes as well, so
  they do not even start.
* **JavaScript-driven motion is not covered.** If you animate with JS, check
  `window.matchMedia("(prefers-reduced-motion: reduce)")` yourself.

The budget is deliberately small: one reveal on arrival, a few 150ms state
changes, and the mark sweep. Nothing loops except the two loading indicators.

---

## 7. Component inventory

`frontend/components/ui/` — 20 `.tsx` files and one hook module. No external UI
library: `clsx` and `tailwind-merge` (as `cn()` in `lib/utils.ts`) are the only
helpers, which is why passing `className` to any of these always wins over the
component's own classes.

Props below are the real exported props. Every component also forwards the
standard HTML attributes of its root element unless noted.

### Alert — `alert.tsx`

Inline notice with a drawn glyph.

| Prop | Type | Default |
|---|---|---|
| `tone` | `"info" \| "positive" \| "danger" \| "accent"` | `"info"` |
| `title` | `ReactNode` | – |
| `live` | `boolean` | – |
| `children` | `ReactNode` | – |

Each tone has its own soft fill, border and glyph path. **Accessibility:**
`role="alert"` when `tone="danger"` or `live` is set, otherwise `role="note"` —
an error announces itself, an informational note does not interrupt. The glyph
is `aria-hidden`.

### Avatar — `avatar.tsx`

| Prop | Type | Default |
|---|---|---|
| `name` | `string` | required |
| `src` | `string \| null` | – |
| `size` | `"sm" \| "md" \| "lg"` | `"md"` (28 / 36 / 48px) |

Falls back to mono initials from `lib/format.ts` → `initials()`.
**Accessibility:** the image is `alt=""` and the initials are `aria-hidden`; the
name is always present as `sr-only` text, so the accessible name is the same
whether or not an image loaded.

### Badge, CountBadge — `badge.tsx`

`Badge` is a pill.

| Prop | Type | Default |
|---|---|---|
| `tone` | `"neutral" \| "accent" \| "positive" \| "danger" \| "info" \| "outline"` | `"neutral"` |
| `mono` | `boolean` | `false` — switches to mono `text-2xs` uppercase, 0.12em tracking |
| `dot` | `boolean` | `false` — a 6px `bg-current` dot |

`CountBadge` is the number on the Recognitions nav item.

| Prop | Type | Default |
|---|---|---|
| `count` | `number` | required — renders nothing at 0 or less |
| `max` | `number` | `9` — above it shows `9+` |
| `label` | `string` | required |

**Accessibility:** the digits are `aria-hidden` and `label` is read instead, in
full ("3 unread Recognitions"). A screen reader hears a sentence, not "3".

### Button, buttonStyles — `button.tsx`

| Prop | Type | Default |
|---|---|---|
| `variant` | `"primary" \| "secondary" \| "ghost" \| "danger" \| "accent"` | `"primary"` |
| `size` | `"sm" \| "md" \| "lg"` | `"md"` (32 / 40 / 48px tall) |
| `loading` | `boolean` | `false` |
| `loadingText` | `string` | – |
| `fullWidth` | `boolean` | `false` |
| `type` | HTML | `"button"` — not `"submit"`, on purpose |

`primary` is filled with **ink**, not accent. `accent` exists for the rare
Recognition-moment action. States: hover, `active:translate-y-px`, disabled
(pointer-events off, no press), loading.

Without `loadingText`, the label is kept in place as `invisible` and a spinner
is absolutely centred over it, so the button does not change width and the
layout does not jump. **Accessibility:** `aria-busy` while loading, the button
is disabled while loading, and an `sr-only` "Working…" is announced.

`buttonStyles(variant, size, className)` returns the same class string for a
`next/link` that should look like a button — used by `not-found.tsx` and the
marketing pages. A link must not be a `<button>`, and a button must not be a
link; this is how both get the same appearance.

### Card and its parts — `card.tsx`

| Prop | Type | Default |
|---|---|---|
| `tone` | `"default" \| "sunken" \| "recognition"` | `"default"` |
| `as` | `"div" \| "article" \| "section" \| "li"` | `"div"` |

`tone="recognition"` is the only place the accent becomes structural: `shadow-lift`
plus a 2px accent left edge. `as` exists so a list of cards is `li` inside a
`ul` rather than divs — keep using it; it is what makes a card list navigable.

Sub-components: `CardHeader`, `CardTitle` (serif, `text-lg`, renders `h3`),
`CardDescription` (`text-sm`, `ink-muted`), `CardBody`, `CardFooter` (top
border, wraps).

### Chip, Segmented — `chip.tsx`

`Chip` is the correction-reason chip.

| Prop | Type |
|---|---|
| `selected` | `boolean` |
| `hint` | `string` — a second line inside the chip |

**Accessibility, and a deliberate decision:** it is a real toggle button with
`aria-pressed`, not a styled radio. The choice is optional — a person may
correct a card without naming a category — and a radio group with no empty
option would make that impossible. Do not "fix" this into a radio group.

`Segmented` is two or three mutually exclusive options.

| Prop | Type |
|---|---|
| `value` | `T extends string` |
| `onChange` | `(value: T) => void` |
| `options` | `readonly { value: T; label: string }[]` |
| `aria-label` | `string` — **required** |

**Accessibility:** `role="radiogroup"` with `role="radio"` and `aria-checked`
children. The required `aria-label` is enforced by the type.

### Dialog — `dialog.tsx`

| Prop | Type | Default |
|---|---|---|
| `open` | `boolean` | required |
| `onClose` | `() => void` | required |
| `title` | `ReactNode` | required |
| `description` | `ReactNode` | – |
| `footer` | `ReactNode` | – |
| `size` | `"sm" \| "md" \| "lg"` | `"md"` (`max-w-sm` / `lg` / `2xl`) |
| `dismissible` | `boolean` | `true` |

Rendered through `createPortal` into `document.body`, gated on `useMounted()`
so it never runs during server rendering. Bottom-aligned on phones,
centred from `sm`. Body scrolls at `max-h-[60vh]`. Footer buttons stack
`flex-col-reverse` on phones (primary at the bottom, nearest the thumb) and sit
right-aligned from `sm`.

`dismissible={false}` removes the close button and ignores Escape and backdrop
clicks — for a destructive confirmation only.

**Accessibility:** `role="dialog"`, `aria-modal="true"`,
`aria-labelledby` and `aria-describedby` wired to generated ids, plus everything
`useModalBehaviour` provides (below).

### EmptyState — `empty-state.tsx`

| Prop | Type |
|---|---|
| `title` | `ReactNode` |
| `description` | `ReactNode` |
| `icon` | `ReactNode` — "a line drawing, not an emoji" |
| `action` | `ReactNode` |
| `footnote` | `ReactNode` — e.g. why the wait is deliberate |

Dashed `line-strong` border on `bg-sunken/60`, centred, serif `text-lg` title.
The `footnote` slot exists because KnoRI's empty states often have to explain
that nothing is wrong — a Recognition genuinely needs two days.

### Field, useFieldContext — `field.tsx`

The one to reach for on any form.

| Prop | Type |
|---|---|
| `label` | `ReactNode` |
| `children` | `ReactNode` — the control |
| `hint` | `ReactNode` — shown until an error replaces it |
| `error` | `string \| undefined` |
| `optional` | `boolean` |
| `action` | `ReactNode` — right-aligned beside the label, e.g. "Forgot?" |

**Accessibility, and the reason this exists:** `Field` generates the id, wires
`aria-describedby` to the hint and error, and sets the invalid flag — then
publishes all three on a context. `Input`, `Textarea` and `Select` read them
with `useFieldContext()`. A label and its error therefore **cannot** drift apart,
because neither is wired by hand. The error line carries its own glyph and
`danger` text; the hint is removed while an error is showing, so there is one
message, not two.

### Input, controlStyles — `input.tsx`

| Prop | Type |
|---|---|
| `leading` | `ReactNode` — decorative glyph on the left, `aria-hidden` |

Plus all `<input>` attributes. `controlStyles` is exported and shared by
`Textarea` and `Select`, so the three controls cannot drift: `surface` fill,
`line-strong` border, inset top shadow, hover border, focus ring plus focus
border, disabled `sunken`, and `aria-[invalid=true]` turning the border and ring
`danger`.

### Label — `label.tsx`

| Prop | Type |
|---|---|
| `optional` | `boolean` |

`optional` prints the word "optional" in muted small text rather than marking
every other field with an asterisk — a positive statement instead of a negative
one everywhere else.

### Select — `select.tsx`

A native `<select>` with `appearance-none`, `controlStyles` and a drawn chevron.
Deliberately native: "the platform gets to draw the list — which on a phone is a
far better control than anything we would build." Reads the field context like
the other controls.

### Sheet — `sheet.tsx`

| Prop | Type | Default |
|---|---|---|
| `open` | `boolean` | required |
| `onClose` | `() => void` | required |
| `title` | `ReactNode` | required |
| `description` | `ReactNode` | – |
| `children` | `ReactNode` | required |
| `footer` | `ReactNode` | – |
| `side` | `"right" \| "left"` | `"right"` — desktop only |

A bottom sheet below 640px, a side panel from 640px up, with the matching
`sheet-up` / `sheet-right` / `sheet-left` animation behind `motion-safe:`.
`max-h-[88vh]` on phones with its own scroll region.

The grab handle and the rounded top edge are for thumbs, not decoration:
**correcting a Recognition happens in this component**, and it has to be
comfortable to type in on a phone. Same accessibility wiring as Dialog.

### Skeleton, SkeletonText — `skeleton.tsx`

`Skeleton` takes `className` only — you give it the shape. `SkeletonText` takes
`lines` (default 3) and renders the last line at 60% width.

The shimmer is a `::after` gradient animated with `sweep`, so the global
reduced-motion rule turns it into a flat tint with no extra code.
**Accessibility:** `aria-hidden` — a skeleton is not content. Announce loading
with a `Spinner` that has a label, as `app-gate.tsx` does with an `sr-only`
spinner beside its skeletons.

### Spinner — `spinner.tsx`

| Prop | Type | Default |
|---|---|---|
| `label` | `string \| null` | `"Loading"` |

With a label: `role="status"`, `aria-live="polite"`, and the label as `sr-only`.
With `label={null}`: no role at all — for use inside a `Button` that already
announces `aria-busy` and "Working…", so the same thing is not said twice.

### Switch — `switch.tsx`

| Prop | Type |
|---|---|
| `checked` | `boolean` |
| `onCheckedChange` | `(checked: boolean) => void` |
| `label` | `ReactNode` |
| `description` | `ReactNode` |
| `disabled` | `boolean` |
| `id` | `string` |

44×24px track, 18px thumb, 200ms transition, accent when on.
**Accessibility:** the label is part of the component rather than a sibling, so
the hit area and the accessible name cannot drift apart. `role="switch"` with
`aria-checked`, a real `<label htmlFor>`, and `aria-describedby` pointing at the
description when there is one.

### Tabs, TabsList, Tab, TabPanel — `tabs.tsx`

`Tabs` is controlled (`value` + `onValueChange`) or uncontrolled
(`defaultValue`). `TabsList` **requires** `aria-label` — "a tablist without a
name is unusable with a screen reader" — and scrolls horizontally with its
scrollbar hidden. `Tab` takes `value`, an optional `count`, and `disabled`.
`TabPanel` takes `value` and renders nothing when inactive.

**Accessibility:** full ARIA tabs pattern. `role="tablist"` / `"tab"` /
`"tabpanel"`, `aria-selected`, `aria-controls` and `aria-labelledby` paired by
generated id, roving `tabIndex` (only the selected tab is in the tab order), and
keyboard handling for ArrowLeft, ArrowRight, Home and End with wraparound,
skipping disabled tabs. The panel itself is focusable so the keyboard lands in
the content after the tab. This is a lot of behaviour in 180 lines — if you
restyle the tabs, change classes only and leave the keyboard handler alone.

### Textarea — `textarea.tsx`

| Prop | Type | Default |
|---|---|---|
| `autoResize` | `boolean` | `false` |
| `maxRows` | `number` | `12` |
| `rows` | `number` | `4` |

With `autoResize` it grows to `maxRows` by measuring computed line height, then
scrolls. Shares `controlStyles` and the field context. The chat composer uses
`rows={1} maxRows={12}`; the correction sheet uses `rows={4} maxRows={10}`.

### ToastProvider, useToast — `toast.tsx`

Mounted once in `app/providers.tsx`. `useToast()` returns `{ toast, dismiss }`.

`toast(options)` takes:

| Field | Type | Default |
|---|---|---|
| `title` | `string` | required |
| `description` | `string` | – |
| `tone` | `"neutral" \| "positive" \| "danger" \| "accent"` | `"neutral"` |
| `duration` | `number` ms | `5000`; **`0` keeps it until dismissed** |
| `action` | `{ label, onClick }` | – |

Tone shows as a 2px coloured left edge. At most four are kept
(`current.slice(-3)` plus the new one). Bottom-centre on phones, bottom-right
from `sm`. All timers are cleared on unmount.

`duration: 0` is the right choice for an error carrying a request id — a person
needs time to copy it. `lib/use-error-toast.ts` does this for you.

**Accessibility:** the container is `aria-live="polite"` with
`aria-relevant="additions"`; each toast is `role="status"`; the dismiss button
has `aria-label="Dismiss notification"`. The container is
`pointer-events-none` and each toast `pointer-events-auto`, so a toast never
blocks a click on the page behind it.

### Tooltip — `tooltip.tsx`

| Prop | Type | Default |
|---|---|---|
| `content` | `ReactNode` | required |
| `side` | `"top" \| "bottom"` | `"top"` |
| `width` | `"sm" \| "md"` | `"md"` (176 / 256px) |

**Accessibility:** the trigger is always a real `<button>`, so hover, focus and
tap all reach the same text and a keyboard user is not excluded. Opens on
mouse-enter or focus after a 120ms delay, closes on leave, blur or Escape, and
toggles on click. The bubble is `role="tooltip"` with `aria-describedby` wired
when open.

`width="md"` exists because the confidence explanation needs the room — see
section 7.1 of the integration guide for why that text cannot be shortened.

### useModalBehaviour, useMounted — `use-modal.ts`

The shared behaviour behind Dialog and Sheet. `useModalBehaviour({ open,
onClose, dismissible })` returns a ref for the panel and provides:

* a **focus trap** — Tab and Shift+Tab cycle within the panel, over a live list
  of focusable elements (so a control that appears later is included);
* **Escape to close**, when `dismissible`;
* **page scroll lock**, with right padding added to match the scrollbar width so
  the page does not shift sideways when the dialog opens;
* **initial focus** on the first focusable element, or the panel itself;
* **focus returned to the opener** on close.

`useMounted()` returns true after the first client render, and gates
`createPortal` so overlays never run during server rendering.

Every one of those five is something hand-rolled overlays usually miss. If you
build another overlay, use this hook rather than repeating it.

### Also worth knowing (outside `ui/`)

* `components/icons.tsx` — 30 icons on one 20-unit grid, 1.6 stroke,
  `currentColor`, all `aria-hidden` and `focusable="false"`. They match text
  weight because they share the stroke, so they stay matched when you change
  font size. No emoji, anywhere, on purpose.
* `components/wordmark.tsx` — the name with the 2px accent rule under it, three
  sizes, optionally a link with `sr-only` "KnoRI home". The rule is the one
  motif the product borrows — a line drawn under words that turned out to
  matter — and it appears here, beside evidence quotes, and nowhere else.
* `components/theme.tsx` — `ThemeProvider`, `ThemeToggle`, `useTheme()` and the
  pre-paint `themeScript`.
* `components/shell/app-shell.tsx` — the left rail (`md:flex`, 76px) and the
  bottom tab bar (`md:hidden`). Two details to keep if you restyle it: the
  active item carries `aria-current="page"` as well as its colour and accent
  marker, and the tab bar adds `paddingBottom: env(safe-area-inset-bottom)` so
  it clears the home indicator on an iPhone.

---

## 8. A short checklist before you open a pull request

* Tokens, not literals. `text-ink-muted`, never `text-[#756c61]`.
* Checked in **both** themes. Press the toggle.
* Checked at **360px** wide. No horizontal scroll, 16px gutter.
* Every interactive element has a visible focus ring.
* The accent appears only where section 2 lists it.
* Serif for what KnoRI says about the person; sans for what the product says
  about itself.
* New colour added in all three token blocks and mapped in `@theme inline`.
* Overlay behaviour comes from `useModalBehaviour`, not from new code.
* Anything animated disappears under `prefers-reduced-motion`.
* `npm run lint`, `npx tsc --noEmit`, `npm run test` all clean; `npm run build`
  clean with the dev server **stopped**.
