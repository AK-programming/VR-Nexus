# VR-Nexus frontend — production image.
#
# Two stages: build the Vite app with Node, then serve the static bundle with
# nginx. nginx also reverse-proxies /api and /ws to the api service, so the
# browser only ever makes same-origin requests — the same arrangement the dev
# Vite proxy provides (myapp/vite.config.ts), which is why VITE_API_BASE_URL is
# left empty and the client builds relative URLs.
#
# This is only used by docker-compose.prod.yml. Local development still runs
# `npm run dev` and talks to the API through Vite's proxy; nothing here changes
# that path.

# ---- build ----
FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json* ./
# npm install (not npm ci) so a lockfile that has not yet been regenerated after
# a dependency change still builds. Switch to `npm ci` once package-lock.json is
# committed in sync for reproducible builds.
RUN npm install --no-audit --no-fund
COPY . .
RUN npm run build

# ---- serve ----
FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
