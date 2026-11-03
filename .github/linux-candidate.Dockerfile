ARG BASE_IMAGE
FROM ${BASE_IMAGE}
# Tool preparation can use Debian's package mirrors; actual source builds are offline.
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc git libc6-dev \
    && dpkg-query -W gcc git libc6-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*
