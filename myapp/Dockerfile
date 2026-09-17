# VR-Nexus frontend — multi-stage build.
#
# Stage 1: Node 20 builds the Vite/React app into static files.
# Stage 2: nginx serves those files and proxies /api + /ws to the backend.

# ---- Build stage ----
FROM node:20-alpine AS build

WORKDIR /app

# Install dependencies first (layer caching).
COPY package.json package-lock.json ./
RUN npm ci

# Copy source and build.
COPY . .

# VITE_API_BASE_URL is empty by default, which means all API calls use relative
# paths (e.g. /api/tenders). This works because nginx proxies /api to the
# backend. Override at build time if the API lives on a different domain.
ARG VITE_API_BASE_URL=""
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL

RUN npm run build

# ---- Serve stage ----
FROM nginx:alpine

# Remove the default nginx config.
RUN rm /etc/nginx/conf.d/default.conf

# Copy our config and the built static files.
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
