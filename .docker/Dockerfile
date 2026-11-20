FROM ghcr.io/astral-sh/uv:0.13.9 AS uv

FROM python:3.14.9-slim-trixie AS builder
COPY --from=uv /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_NO_DEV=1
WORKDIR /app
# Dependencies first, in their own layer, so code changes don't reinstall them.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-editable

FROM python:3.14.9-slim-trixie
# Debian (not Alpine) for LibreOffice and ffmpeg from its packages. Apply security fixes newer than the base
# tag, and drop the base image's pip: the app runs from its own venv, so pip is only unused attack surface.
# LibreOffice Writer without its GUI converts documents to PDF. The fonts match the metrics of Word's defaults
# (Liberation: Arial, Times New Roman, Courier New; Carlito: Calibri; Caladea: Cambria), so layouts keep their line
# breaks; DejaVu covers other scripts such as Cyrillic and Greek. ffmpeg (with ffprobe) converts and merges YouTube
# downloads; Deno, which solves YouTube's challenges, comes from PyPI with yt-dlp.
RUN apt-get update \
    && apt-get upgrade --yes --no-install-recommends \
    && apt-get install --yes --no-install-recommends \
        libreoffice-writer-nogui fonts-liberation fonts-crosextra-carlito fonts-crosextra-caladea fonts-dejavu-core \
        ffmpeg \
    && rm -rf /var/lib/apt/lists/* \
    && python -m pip uninstall --yes --quiet --root-user-action=ignore pip \
    && rm -rf /usr/local/lib/python3.14/ensurepip \
    && groupadd --system --gid 10001 tgmate \
    && useradd --system --uid 10001 --gid tgmate --no-create-home --shell /usr/sbin/nologin tgmate \
    && install -d -o tgmate -g tgmate /data
COPY --from=builder --chown=tgmate:tgmate /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    DATABASE_URL=sqlite+aiosqlite:////data/tgmate.db
WORKDIR /data
VOLUME /data
USER tgmate
CMD ["python", "-m", "tgmate.telegram"]
