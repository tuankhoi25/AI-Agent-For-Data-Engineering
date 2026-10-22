# syntax=docker/dockerfile:1
ARG TARGETARCH
FROM alpine:3.23.3 AS dagu-arm64
ADD --checksum=sha256:a03d1ab129d25323002e32b161870081b9db6e09d4bc455705725ccf9d846e74 \
    https://github.com/dagucloud/dagu/releases/download/v2.21.0/dagu_2.21.0_linux_arm64.tar.gz /tmp/dagu.tar.gz
RUN tar -xzf /tmp/dagu.tar.gz -C /usr/local/bin dagu

FROM alpine:3.23.3 AS dagu-amd64
ADD --checksum=sha256:4004de798006e4b70d8002f287f0389f34a8271baec380bccf60b710f0ae0f75 \
    https://github.com/dagucloud/dagu/releases/download/v2.21.0/dagu_2.21.0_linux_amd64.tar.gz /tmp/dagu.tar.gz
RUN tar -xzf /tmp/dagu.tar.gz -C /usr/local/bin dagu

FROM dagu-${TARGETARCH} AS dagu-binary

FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    VIRTUAL_ENV=/opt/bakery/.venv \
    PATH="/opt/bakery/.venv/bin:$PATH" \
    PYTHONPATH=/opt/bakery/data_platform/dagu:/opt/bakery/analytics \
    DAGU_HOME=/var/lib/dagu DAGU_HOST=0.0.0.0 DAGU_PORT=8080 \
    TZ=Asia/Ho_Chi_Minh
COPY --from=dagu-binary /usr/local/bin/dagu /usr/local/bin/dagu
RUN python -m venv /opt/bakery/.venv
COPY requirements.txt /tmp/dagu-requirements.txt
RUN pip install -r /tmp/dagu-requirements.txt && pip check
WORKDIR /opt/bakery
CMD ["dagu", "start-all", "--config", "/opt/bakery/data_platform/dagu/config.yaml"]

