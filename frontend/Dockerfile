# Stage 1: Build the React frontend
FROM node:18 AS builder

WORKDIR /app
COPY package*.json ./
RUN npm install

COPY . .
RUN npm run build

# Stage 2: Serve with Nginx
FROM nginx:alpine

# Remove default Nginx static assets
RUN rm -rf /usr/share/nginx/html/*

# ✅ Copy CRA build files instead of dist
COPY --from=builder /app/build /usr/share/nginx/html

# Optional: copy custom nginx config
# COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
