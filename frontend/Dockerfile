# syntax=docker/dockerfile:1

# Production frontend image: Vite builds the SPA, nginx serves the static
# bundle and proxies the API on the same origin. No Node process runs in the
# shipped container.

# ---- build stage ----
FROM node:20-alpine AS build
WORKDIR /app

# Relative API by default: the browser calls /api and /healthz, and nginx
# proxies them to the api service. Set VITE_API_ORIGIN to target another host.
ARG VITE_API_ORIGIN=""
ENV VITE_API_ORIGIN=${VITE_API_ORIGIN}

COPY package.json package-lock.json ./
RUN npm ci

COPY index.html tsconfig.json vite.config.ts ./
COPY src ./src
RUN npm run build

# ---- serve stage ----
FROM nginx:1.27-alpine AS serve

# The nginx entrypoint renders nginx/default.conf.template into conf.d at
# container start, substituting this upstream. Keep it in step with the
# compose `api` service name.
ENV RAO_API_UPSTREAM=api:8000

COPY nginx/default.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
