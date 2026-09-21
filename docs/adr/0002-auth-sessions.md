# ADR-002 — Opaque session cookies, not JWTs

**Status:** accepted · **Date:** Phase 1 planning · **Source:** `plan.md` §7

## Context

KnoRI holds the most personal thing a product can hold: what someone said about
themselves, and what a machine concluded from it. Two of the eleven Phase 1 outcomes
are about trust and control.

That makes some authentication requirements non-negotiable:

* **"Log out everywhere" must work immediately.** Someone who thinks their account is
  compromised needs every other session dead now, not in fifteen minutes.
* **Deleting an account must actually end its sessions**, inside the same transaction
  that marks it for deletion.
* **A database dump must not be a set of working logins.**

A stateless JWT is the opposite of the first two. Its whole point is that the server
does not need to look anything up, which means a token stays valid until it expires
regardless of what has happened to the account. Every workaround — short expiry with
refresh tokens, a denylist, a per-user token version — adds back the database read
that the JWT was supposed to avoid, plus key rotation to get wrong.

## Decision

**Opaque random session tokens, stored hashed, in an httpOnly cookie.**

* 32 random bytes from `secrets`, base64url encoded.
* Only `sha256(token)` is stored, in `auth_sessions.token_hash` (unique). The token
  itself exists only in the user's cookie.
* The cookie is `HttpOnly; Secure; SameSite=Lax; Path=/`, 30 days, sliding —
  `last_seen_at` is refreshed as the session is used.
* `Secure` is omitted only when `API_URL` starts with `http://`, which is local
  development.
* CSRF: an `Origin` check **plus** a required `X-Requested-With: knori` header on every
  non-GET request that carries the cookie. A cross-site HTML form can set neither.
* Passwords: argon2id, 64 MiB, 3 passes, 4 lanes, minimum 10 characters, re-hashed on
  login when the parameters change.

SHA-256 for tokens and argon2id for passwords is a deliberate split, not an
inconsistency. A session token already contains 256 bits of entropy, so there is
nothing to brute force and the lookup must be fast on every request. A password is
chosen by a human, so it needs to be slow to guess.

## Consequences

**Good.**

* Revocation is a single `UPDATE`. "Log out everywhere" is one statement. So is
  ending sessions during account deletion, in the same transaction.
* A stolen database gives an attacker hashes, not logins.
* No signing keys, so no key rotation and no key-confusion vulnerability class.
* `SameSite=Lax` plus the header check means no CSRF token has to be minted, stored,
  rotated or debugged.
* Session state is visible: `SELECT … FROM auth_sessions WHERE user_id = …` answers
  "where am I signed in?" directly.

**Costs, accepted.**

* One indexed database read per authenticated request. It is a primary-key-shaped
  lookup on a small table, and the API is already talking to Postgres on every
  request.
* Sessions cannot be validated at the edge or by another service. There is one api
  process; there is no edge.
* Horizontal scaling needs shared database access — which everything already needs.

**Deliberately not done.**

* No per-device session list. Phase 1 has "log out everywhere" only (`plan.md` §2.3).
* No social login. That is a change request.
* No Row-Level Security. The repository layer filters by `user_id` on every query and
  every endpoint has a cross-user test; RLS was scheduled as buffer-week hardening.

## When to revisit

If KnoRI ever grows a second service that must authenticate a request without reaching
the database, or an edge layer that should reject traffic before it arrives. Neither
exists.
