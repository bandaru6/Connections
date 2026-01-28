# Frontend Dockerfile - Next.js
FROM --platform=linux/amd64 node:20-alpine

WORKDIR /app

# Install dependencies
COPY package*.json ./
RUN npm ci

# Copy source
COPY . .

# Build
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

# Run
ENV NODE_ENV=production
EXPOSE 3000

CMD ["npm", "start"]
