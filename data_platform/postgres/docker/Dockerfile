FROM postgres:16-bookworm AS base

# Compile against the same PostgreSQL base used by the runtime image.
FROM base AS builder
ARG PG_DUCKDB_VERSION=v1.1.1
ARG PG_DUCKDB_BUILD_JOBS=2

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        postgresql-server-dev-16 \
        build-essential libreadline-dev zlib1g-dev flex bison libxml2-dev \
        libxslt-dev libssl-dev libxml2-utils xsltproc pkg-config libc++-dev \
        libc++abi-dev libglib2.0-dev libtinfo5 cmake libstdc++-12-dev \
        liblz4-dev ninja-build git libcurl4-openssl-dev ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build/pg_duckdb
RUN git clone --branch "$PG_DUCKDB_VERSION" --depth 1 --recurse-submodules \
    --shallow-submodules https://github.com/duckdb/pg_duckdb.git .

RUN case "$PG_DUCKDB_BUILD_JOBS" in ''|*[!0-9]*) exit 1 ;; esac \
    && test "$PG_DUCKDB_BUILD_JOBS" -gt 0 \
    && CMAKE_BUILD_PARALLEL_LEVEL="$PG_DUCKDB_BUILD_JOBS" \
        make -j"$PG_DUCKDB_BUILD_JOBS" PG_CONFIG=/usr/lib/postgresql/16/bin/pg_config \
    && make install DESTDIR=/out PG_CONFIG=/usr/lib/postgresql/16/bin/pg_config

# Keep compilers, development packages, and source code out of the runtime.
FROM base AS runtime
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates libcurl4 liblz4-1 libstdc++6 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /out/ /

# Fail the build if extension artifacts or their runtime dependencies are missing.
RUN test -s /usr/lib/postgresql/16/lib/pg_duckdb.so \
    && test -s /usr/lib/postgresql/16/lib/libduckdb.so \
    && test -s /usr/share/postgresql/16/extension/pg_duckdb.control \
    && ldd /usr/lib/postgresql/16/lib/pg_duckdb.so \
    && ! ldd /usr/lib/postgresql/16/lib/pg_duckdb.so | grep -q 'not found'

# Inherit the official image's entrypoint, user switching, and init SQL handling.
