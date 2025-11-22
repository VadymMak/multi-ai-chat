FROM node:18-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .

# Build-time environment variable (важно: перед build!)
ARG VITE_API_URL=https://multi-ai-chat-production.up.railway.app
ENV VITE_API_URL=$VITE_API_URL

RUN npm run build:production

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]