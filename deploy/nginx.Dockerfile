# Prepare frontend assets (shop_interior, counter_foreground, sprites)
FROM python:3.12-slim AS assets

WORKDIR /prep
COPY assets/ assets/
COPY scripts/prepare_assets.sh scripts/cut_window_mask.py scripts/slice_counter.py scripts/
RUN mkdir -p demo/window/public/assets/sprites
RUN pip install --no-cache-dir Pillow \
    && bash scripts/prepare_assets.sh

# Build the Next.js frontend, then serve via nginx
FROM node:20-alpine AS frontend

WORKDIR /build
COPY demo/window/package.json demo/window/package-lock.json ./
RUN npm ci --silent
COPY demo/window/ ./
COPY --from=assets /prep/demo/window/public/assets/ public/assets/
RUN npm run build
# Output: /build/out/ (static export)

FROM nginx:1.27-alpine

# Copy built frontend
COPY --from=frontend /build/out /var/www/shopkeeper

# Default config is mounted via docker-compose volume
