FROM node:18-alpine AS frontend-build

WORKDIR /app
COPY frontend/package*.json ./
ARG REACT_APP_API_URL=/api
RUN npm install
COPY frontend/ .
RUN REACT_APP_API_URL=${REACT_APP_API_URL} npm run build

FROM nginx:alpine

RUN rm /etc/nginx/conf.d/default.conf

COPY --from=frontend-build /app/build /usr/share/nginx/html
COPY nginx/nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
