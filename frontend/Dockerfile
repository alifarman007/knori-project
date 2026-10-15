# syntax=docker/dockerfile:1.7
# KnoRI web app. Build context is frontend/ :
#
#   docker build -t knori-web frontend
#
# Three stages: install, build, run. Only the third ends up in the image, so
# node_modules and the toolchain are not shipped.
#
# NEXT_PUBLIC_* values are compiled into the browser bundle, so they are build
# arguments, not run-time environment. PORT is read at run time.

# ------------------------------------------------------------------- deps
FROM node:22-alpine AS deps
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
# Lockfile only, so this layer is reused until a dependency actually changes.
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

# ------------------------------------------------------------------- build
FROM node:22-alpine AS build
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1 \
    NODE_ENV=production
COPY --from=deps /app/node_modules ./node_modules
COPY . .

# Empty means same-origin: lib/api.ts then calls /api/v1, Caddy routes that to the
# API, and the httpOnly session cookie stays first-party. Set NEXT_PUBLIC_API_URL
# only for a deployment where the web app and the API are not behind one host — the
# API must then send SameSite=None.
ARG NEXT_PUBLIC_API_BASE=""
ARG NEXT_PUBLIC_API_URL=""
# Used for metadataBase in app/layout.tsx (absolute URLs in page metadata).
ARG NEXT_PUBLIC_SITE_URL=""
# Where the Next server forwards /api/* if a request reaches it directly. Behind
# Caddy it never does, because Caddy matches /api/* first; this is the fallback for
# running the web container on its own.
ARG KNORI_API_ORIGIN="http://api:8000"

# An ARG exports its value into the environment of every RUN in the stage, so an
# ARG left at "" arrives as an empty string rather than as unset. That matters:
# app/layout.tsx does `new URL(process.env.NEXT_PUBLIC_SITE_URL ?? "...")`, Next
# inlines the empty string at build time, `??` is satisfied by it, and the build
# fails with `Invalid URL` while collecting page data. Clearing the empty ones is
# what makes "not passed" mean "not set".
RUN set -eu; \
    for var in NEXT_PUBLIC_API_BASE NEXT_PUBLIC_API_URL NEXT_PUBLIC_SITE_URL KNORI_API_ORIGIN; do \
        eval "value=\${$var-}"; \
        [ -n "$value" ] || unset "$var"; \
    done; \
    echo "--- build-time configuration ---"; \
    { env | grep -E '^(NEXT_PUBLIC_|KNORI_API_ORIGIN=)' || echo "  (all defaults)"; }; \
    npm run build

# ------------------------------------------------------------------- run
FROM node:22-alpine AS run
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

# server.js reads HOSTNAME, and Docker sets it to the container id by default, so
# it is pinned above — otherwise the server binds to a name nothing else resolves.
# The node image already has an unprivileged `node` user (uid 1000).
COPY --from=build --chown=node:node /app/.next/standalone ./
COPY --from=build --chown=node:node /app/.next/static ./.next/static
# There is no frontend/public directory in this repository; add a third COPY here
# if one is ever added.

USER node
EXPOSE 3000

HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
    CMD ["node", "-e", "fetch('http://127.0.0.1:'+(process.env.PORT||3000)+'/').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"]

CMD ["node", "server.js"]
