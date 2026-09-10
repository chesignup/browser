FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
      openssh-server tmux curl ca-certificates python3 python3-pip \
      git iproute2 iptables iputils-ping socat jq vim-tiny less procps \
    && rm -rf /var/lib/apt/lists/*

# Tailscale (its own tailnet node; brought up interactively at runtime)
RUN curl -fsSL https://tailscale.com/install.sh | sh

# Cursor CLI (installs `cursor-agent`/`agent` into /root/.local/bin)
RUN curl https://cursor.com/install -fsS | bash

# Python deps: human_browser control layer (mounted at /opt/human_browser) + MCP
# (the human-browser MCP app is mounted at /app and run over stdio for the CLI).
RUN pip3 install --break-system-packages --no-cache-dir websockets "mcp>=1.9,<2"

RUN mkdir -p /var/run/sshd /root/.ssh /root/.cursor \
    && sed -i 's/#\?PermitRootLogin.*/PermitRootLogin yes/' /etc/ssh/sshd_config \
    && sed -i 's/#\?PasswordAuthentication.*/PasswordAuthentication yes/' /etc/ssh/sshd_config \
    && printf '\n# Drop SSH logins into the ONE shared agent tmux session (attach or create; -D detaches other clients so each login is full-size)\nForceCommand tmux new-session -A -D -s agent /usr/local/bin/agent-run\n' >> /etc/ssh/sshd_config \
    && printf '\nexport PATH=/root/.local/bin:$PATH\n' >> /root/.bashrc

ENV PATH=/root/.local/bin:$PATH
ENV PYTHONPATH=/opt/human_browser
ENV GUEST_HOST=100.92.122.70

COPY gbrowser /usr/local/bin/gbrowser
COPY agent-run /usr/local/bin/agent-run
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
COPY skill/ /root/.cursor/skills/
COPY mcp.json /root/.cursor/mcp.json
RUN chmod +x /usr/local/bin/gbrowser /usr/local/bin/agent-run /usr/local/bin/entrypoint.sh

EXPOSE 22
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
