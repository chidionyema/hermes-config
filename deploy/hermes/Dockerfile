# syntax=docker/dockerfile:1.7
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
    && /opt/venv/bin/pip install --no-cache-dir -e ./hermes-agent \
    && /opt/venv/bin/pip install --no-cache-dir numpy
ENV PATH=/opt/venv/bin:$PATH

# THE DAEMONS DO NOT USE $PATH. coordinator-daemon.sh:25 and cockpit-daemon.sh:36 exec
# /usr/local/bin/python3 by absolute path, so putting the venv on PATH does nothing for
# them: the first smoke test had coordinator dead on "No module named httpx" and cockpit
# dead on "No module named uvicorn" while both packages sat installed in /opt/venv.
#
# The absolute paths are not a mistake to fix here - they are what runs on the laptop, and
# a script edited only for the image is a script that drifts. So the image makes the base
# interpreter see the venv instead.
#
# site.addsitedir, not a bare path line: a bare path in a .pth is appended to sys.path and
# nothing else, whereas addsitedir also processes the .pth files it finds - which is how
# the editable install of hermes-agent gets registered. A bare path would import httpx and
# still fail to import hermes-agent's own modules.
#
# Re-pointing /usr/local/bin/python3 at the venv is NOT an option: /opt/venv/bin/python is
# itself a symlink to /usr/local/bin/python, so that is a loop.
RUN printf "%s\n" "import site; site.addsitedir('/opt/venv/lib/python3.11/site-packages')" \
      > /usr/local/lib/python3.11/site-packages/hermes-venv.pth \
 && /usr/local/bin/python3 -c "import httpx, uvicorn, fastapi; print('base interpreter sees the venv')"

COPY . .

# The laptop's gateway runs `hermes-agent/venv/bin/python`. That path is baked into
# scripts, so it is made to exist and point at the venv this image built.
RUN mkdir -p hermes-agent/venv/bin \
    && ln -sf /opt/venv/bin/python hermes-agent/venv/bin/python \
    && ln -sf /opt/venv/bin/pip hermes-agent/venv/bin/pip

# HERMES IS NOT ONE REPO. cockpit-daemon.sh:35 cds into ~/Documents/code/sentinel-loop and
# otto-daemon.sh:80 runs a script from inside it. Neither is part of the Hermes checkout, so
# the first image built fine and then had cockpit and otto-server both FATAL on
# "No such file or directory" for a path that exists only on the laptop.
#
# It arrives as a NAMED BUILD CONTEXT rather than a vendored copy inside this repo. A vendored
# copy would be 26 MB of someone else's source committed here and stale from the day it landed;
# a git clone in the build would need a credential for a private repo. A named context needs
# neither - deploy/hermes/build.sh points it at whatever checkout the builder has.
COPY --from=sentinel-loop . /Users/chidionyema/Documents/code/sentinel-loop

COPY deploy/hermes/supervisord.conf /etc/supervisor/conf.d/hermes.conf
COPY deploy/hermes/entrypoint.sh deploy/hermes/periodic.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/entrypoint.sh /usr/local/bin/periodic.sh

# tini, because supervisor's children spawn their own children and a container without
# an init leaks zombies until the pid table fills.
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/entrypoint.sh"]
CMD ["supervisord", "-c", "/etc/supervisor/supervisord.conf", "-n"]
