FROM python:3.12-slim
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
      curl ca-certificates openssh-client iproute2 iptables iputils-ping \
      procps jq \
    && rm -rf /var/lib/apt/lists/*

# Tailscale (own tailnet node; used for guest access + public Funnel exposure)
RUN curl -fsSL https://tailscale.com/install.sh | sh

# MCP server deps (human_browser is mounted at /opt/human_browser at runtime)
RUN pip install --no-cache-dir "mcp>=1.9,<2" uvicorn websockets

ENV PYTHONPATH=/opt/human_browser
ENV GUEST_HOST=100.92.122.70
ENV MCP_PORT=8000

COPY app/ /app/
COPY mcp-expose /usr/local/bin/mcp-expose
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/mcp-expose /usr/local/bin/entrypoint.sh

WORKDIR /app
EXPOSE 8000
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
