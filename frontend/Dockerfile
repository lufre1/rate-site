FROM node:18-alpine AS build
WORKDIR /app

# This host has 3.8 GiB and, until 2026-09-01, no swap at all. A default CRA
# build peaks at 1.5-2 GB in the main process plus one terser worker per core,
# and the machine hard-locked mid-build on 2026-08-31 and 2026-09-01. See the
# "Host memory" section of AGENTS.md.
#   * GENERATE_SOURCEMAP=false is the single biggest win -- it removes source-map
#     generation from both webpack and terser, roughly halving peak RSS and
#     cutting build time. Production source maps are not wanted here anyway.
#   * --max-old-space-size caps each node heap. jest-worker forks inherit the
#     environment, so the terser workers are capped too. The build now FAILS with
#     "JavaScript heap out of memory" instead of taking the machine with it.
# Caveat: this bounds the JS heap, not total RSS, and CRA 5 does not expose
# terser's worker count without ejecting. earlyoom is the backstop.
ENV GENERATE_SOURCEMAP=false
ENV INLINE_RUNTIME_CHUNK=false
ENV CI=true
ENV NODE_OPTIONS=--max-old-space-size=768

COPY package*.json ./
ARG REACT_APP_API_URL=http://localhost:8000
ENV REACT_APP_API_URL=${REACT_APP_API_URL}
RUN npm install --no-audit --no-fund
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/build /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
