FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# FastMCP queries PyPI for a newer release on start-up. A deployed server should
# not reach out to the internet on its own.
ENV FASTMCP_CHECK_FOR_UPDATES=off

# The ASCII banner is noise in service logs; the server logs its own version and
# target instance instead.
ENV FASTMCP_SHOW_SERVER_BANNER=false

# One log format for the whole process; see logging_setup.py.
ENV FASTMCP_ENABLE_RICH_LOGGING=false

WORKDIR /app

RUN groupadd --system oitc && useradd --system --gid oitc --no-create-home oitc

# Dependencies first so a source-only change does not re-resolve them.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY pyproject.toml MCP_VERSION LICENSE README.md ./
COPY src/ ./src/
RUN pip install --no-cache-dir --no-deps .

USER oitc

EXPOSE 8000

# Configuration comes from the environment (see .env.example). No secret is
# baked into the image.
CMD ["oitc-mcp"]
