# Hermes on any box with Docker.
#
# Why this exists: as of 2026-08-18 Hermes ran ONLY on the founder's laptop - twelve
# launchd jobs and no copy anywhere else. Lose the laptop and the Telegram front door,
# the coordinator and the cockpit all go dark at once. That contradicts the rule the
# engine migration was carried out to satisfy: nothing business-critical runs on the
# laptop.
#
# The venv on the laptop is Python 3.11.15, so this is 3.11. A macOS venv is not
# portable, so nothing is copied in - the dependencies are resolved again here against
# Linux wheels.
FROM python:3.11-slim-bookworm

# THE PATH IS THE POINT. Scripts across this repo write /Users/chidionyema/.hermes
# literally, and ~/.hermes resolves through HOME. Recreating both inside the container
# costs one directory and one environment variable, and it removes an entire class of
# migration bug - a path that resolves on the laptop and silently does not here.
ENV HOME=/Users/chidionyema \
    HERMES_HOME=/Users/chidionyema/.hermes \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=Europe/London

RUN apt-get update && apt-get install -y --no-install-recommends \
        bash git curl ca-certificates tini supervisor jq \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /Users/chidionyema/.hermes

# Dependencies first, so a change to a script does not re-resolve the world.
COPY hermes-agent/pyproject.toml hermes-agent/setup.py ./hermes-agent/
COPY hermes-agent/uv.lock ./hermes-agent/
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir -e ./hermes-agent
ENV PATH=/opt/venv/bin:$PATH

COPY . .

# The laptop's gateway runs `hermes-agent/venv/bin/python`. That path is baked into
# scripts, so it is made to exist and point at the venv this image built.
RUN mkdir -p hermes-agent/venv/bin \
    && ln -sf /opt/venv/bin/python hermes-agent/venv/bin/python \
    && ln -sf /opt/venv/bin/pip hermes-agent/venv/bin/pip

COPY deploy/hermes/supervisord.conf /etc/supervisor/conf.d/hermes.conf
COPY deploy/hermes/entrypoint.sh deploy/hermes/periodic.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/entrypoint.sh /usr/local/bin/periodic.sh

# tini, because supervisor's children spawn their own children and a container without
# an init leaks zombies until the pid table fills.
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/entrypoint.sh"]
CMD ["supervisord", "-c", "/etc/supervisor/supervisord.conf", "-n"]
