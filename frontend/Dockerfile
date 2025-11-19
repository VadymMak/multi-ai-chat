FROM node:18-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .

# ✅ Hardcode API URL или использовать ARG правильно
ENV REACT_APP_API_BASE_URL=https://multi-ai-chat-production.up.railway.app/api

RUN npm run build

FROM nginx:alpine
COPY --from=build /app/build /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]