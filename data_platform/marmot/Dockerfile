# Custom Marmot image with the official Dagu brand mark available to the
# frontend asset-logo fallback.
# The application source remains pinned to the upstream v0.11.1 release.

ARG MARMOT_VERSION=0.11.1

FROM alpine:3.23.3 AS source
ARG MARMOT_VERSION
RUN apk add --no-cache ca-certificates curl tar
WORKDIR /src
RUN curl -fsSL "https://github.com/marmotdata/marmot/archive/refs/tags/v${MARMOT_VERSION}.tar.gz" \
    -o /tmp/marmot.tar.gz \
    && tar -xzf /tmp/marmot.tar.gz --strip-components=1 \
    && rm /tmp/marmot.tar.gz
# This is the 512x512 brand mark shipped by the official Dagu repository:
# https://github.com/dagucloud/dagu/blob/main/assets/images/brand-mark.png
# Marmot's IconLoader already checks /images/asset-logos/<provider>.png after
# checking its bundled component icons, so no frontend source patch is needed.
RUN mkdir -p /src/web/marmot/static/images/asset-logos \
    && curl -fsSL "https://raw.githubusercontent.com/dagucloud/dagu/main/assets/images/brand-mark.png" \
       -o /src/web/marmot/static/images/asset-logos/dagu.png

FROM node:22-alpine AS frontend
RUN corepack enable && corepack prepare pnpm@11 --activate
WORKDIR /app/web/marmot
COPY --from=source /src/web/marmot/package.json /src/web/marmot/pnpm-lock.yaml /src/web/marmot/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY --from=source /src/web/marmot/ ./
RUN node scripts/generate-icon-bundle.mjs && pnpm build

FROM golang:1.26 AS builder
WORKDIR /app
COPY --from=source /src/go.mod /src/go.sum ./
COPY --from=source /src/sdk/ sdk/
RUN go mod download
COPY --from=source /src/ ./
COPY --from=frontend /app/web/marmot/build ./internal/staticfiles/build
RUN CGO_ENABLED=0 go build -tags production -ldflags '-s -w' -o marmot ./cmd/main.go

FROM gcr.io/distroless/static-debian12:nonroot
LABEL io.modelcontextprotocol.server.name="io.github.marmotdata/marmot"
COPY --from=builder /app/marmot /usr/local/bin/marmot
EXPOSE 8080
ENTRYPOINT ["/usr/local/bin/marmot"]
CMD ["run"]
