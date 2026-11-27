FROM node:22-alpine AS build

WORKDIR /web
COPY package.json package-lock.json ./
RUN npm ci
COPY . .

ARG VITE_API_BASE_PATH=/api/v1
ARG VITE_USE_MOCK=false
ARG VITE_SUPABASE_URL
ARG VITE_SUPABASE_PUBLISHABLE_KEY
ARG VITE_ADMIN_EMAIL_DOMAIN=team.local
ARG VITE_USER_URL=/

ENV VITE_API_BASE_PATH=${VITE_API_BASE_PATH} \
    VITE_USE_MOCK=${VITE_USE_MOCK} \
    VITE_SUPABASE_URL=${VITE_SUPABASE_URL} \
    VITE_SUPABASE_PUBLISHABLE_KEY=${VITE_SUPABASE_PUBLISHABLE_KEY} \
    VITE_ADMIN_EMAIL_DOMAIN=${VITE_ADMIN_EMAIL_DOMAIN} \
    VITE_USER_URL=${VITE_USER_URL}

RUN npm run build && npm run build:admin

FROM nginx:1.27-alpine AS runtime

COPY nginx/default.conf.template /etc/nginx/templates/
# [NEW] KOS-58 공통 location, HTTPS 템플릿(NGINX_ENVSUBST_TEMPLATE_DIR 로 선택)
COPY nginx/app-locations.conf /etc/nginx/
COPY nginx/tls/default.conf.template /etc/nginx/templates-tls/
COPY --from=build /web/dist/ /usr/share/nginx/html/
COPY --from=build /web/admin/dist/ /usr/share/nginx/html/admin/