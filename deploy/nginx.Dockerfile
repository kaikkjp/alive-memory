# Build the Next.js frontend, then serve via nginx
FROM node:20-alpine AS frontend

WORKDIR /build
COPY window/package.json window/package-lock.json ./
RUN npm ci --silent
COPY window/ ./
RUN npm run build
# Output: /build/out/ (static export)

FROM nginx:1.27-alpine

# Copy built frontend
COPY --from=frontend /build/out /var/www/shopkeeper

# Default config is mounted via docker-compose volume
