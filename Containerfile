# Likewise — container image.
#
# Two stages so the runtime image carries no compiler and no package index. The final
# image runs as an unprivileged user with a read-only root filesystem; everything it
# writes goes to /data, which is a volume.

FROM docker.io/library/python:3.12-slim AS build

WORKDIR /build
COPY requirements.txt .
RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install --no-cache-dir --upgrade pip \
 && /opt/venv/bin/pip install --no-cache-dir -r requirements.txt


FROM docker.io/library/python:3.12-slim

# A fixed uid so a bind-mounted /data has predictable ownership on the host.
RUN groupadd --gid 10001 likewise \
 && useradd --uid 10001 --gid 10001 --home-dir /app --no-create-home likewise

COPY --from=build /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    LIKEWISE_DATA=/data \
    LIKEWISE_STORE=/data/store \
    LIKEWISE_SPECS=/app/specs

WORKDIR /app
COPY likewise/ ./likewise/
COPY specs/ ./specs/
COPY tools/ ./tools/
COPY docs/templates/ ./docs/templates/

# /data holds everything mutable: the drop folder, curated snapshots, scan results.
RUN mkdir -p /data/inbox /data/curated /data/store /data/examples \
 && chown -R 10001:10001 /data /app

USER 10001:10001
EXPOSE 8080

# The specification is validated before the port is bound, so a container that is
# listening is a container holding a valid, digested specification. A failure here
# exits 78 with a machine-readable payload rather than serving anything.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/health',timeout=4).status==200 else 1)"

ENTRYPOINT ["python", "-m", "uvicorn", "likewise.api:app", "--host", "0.0.0.0", "--port", "8080"]
