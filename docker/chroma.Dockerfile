# syntax=docker/dockerfile:1
FROM chromadb/chroma:1.5.9@sha256:1e0b73a187a28757c572acba508c46f48c9e8b0acaf5c20e6d95cdedce1acdf6
USER root
RUN --mount=type=secret,id=cloud_ca,mode=0444 \
    sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources \
    && if [ -s /run/secrets/cloud_ca ]; then echo 'Acquire::https::CaInfo "/run/secrets/cloud_ca";' > /etc/apt/apt.conf.d/90-cloud-ca; fi \
    && apt-get update \
    && apt-get install --no-install-recommends -y curl ca-certificates \
    && rm -rf /var/lib/apt/lists/* /etc/apt/apt.conf.d/90-cloud-ca \
    && groupadd --gid 10001 rag \
    && useradd --uid 10001 --gid rag --no-create-home rag \
    && mkdir -p /data && chown -R rag:rag /data
USER 10001:10001
