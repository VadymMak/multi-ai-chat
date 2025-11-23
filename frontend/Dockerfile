# Cache buster: v3 - Added code detection triggers
FROM node:18-alpine AS build
WORKDIR /app

# Copy package files
COPY package*.json ./
RUN npm install

# Copy source code
COPY . .

# Build-time environment variable
ARG VITE_API_URL=https://multi-ai-chat-production.up.railway.app
ENV VITE_API_URL=$VITE_API_URL

# Build for production
RUN npm run build:production

# Production stage
FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]