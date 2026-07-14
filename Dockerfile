FROM node:24-bookworm-slim AS frequi-builder

WORKDIR /frequi
RUN corepack enable
COPY frequi/package.json frequi/pnpm-lock.yaml frequi/pnpm-workspace.yaml ./
RUN corepack prepare pnpm@11.9.0 --activate \
  && pnpm install --frozen-lockfile
COPY frequi/ ./
RUN pnpm run build

FROM python:3.14.6-slim-trixie AS base

ENV LANG=C.UTF-8
ENV LC_ALL=C.UTF-8
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONFAULTHANDLER=1
ENV PYTHONUSERBASE=/home/ftuser/.local
ENV PATH=/home/ftuser/.local/bin:$PATH
ENV FT_APP_ENV="docker"

RUN mkdir /freqtrade \
  && apt-get update \
  && apt-get -y install --no-install-recommends libatlas3-base curl sqlite3 libgomp1 \
  && apt-get clean \
  && rm -rf /var/lib/apt/lists/* \
  && useradd -u 1000 -U -m -s /bin/bash ftuser \
  && chown ftuser:ftuser /freqtrade

WORKDIR /freqtrade

FROM base AS python-deps

RUN apt-get update \
  && apt-get -y install --no-install-recommends build-essential libssl-dev git libffi-dev libgfortran5 pkg-config cmake gcc \
  && apt-get clean \
  && rm -rf /var/lib/apt/lists/* \
  && pip install --upgrade pip wheel

COPY --chown=ftuser:ftuser freqtrade/requirements.txt freqtrade/requirements-hyperopt.txt /freqtrade/

USER ftuser
RUN pip install --user --no-cache-dir "numpy<3.0" \
  && pip install --user --no-cache-dir -r requirements-hyperopt.txt

FROM base AS runtime-image

COPY --from=python-deps --chown=ftuser:ftuser /home/ftuser/.local /home/ftuser/.local
COPY --chown=ftuser:ftuser freqtrade/ /freqtrade/
COPY --from=frequi-builder --chown=ftuser:ftuser /frequi/dist /freqtrade/freqtrade/rpc/api_server/ui/installed
COPY --chown=root:root --chmod=0555 \
  docker/freqtrade_entrypoint.py \
  /usr/local/bin/freqtrade-entrypoint

USER ftuser
RUN printf '%s\n' 'local-frequi-f5a81466' > /freqtrade/freqtrade/rpc/api_server/ui/.uiversion \
  && pip install -e . --user --no-cache-dir \
  && mkdir -p /freqtrade/user_data/

USER root
RUN chmod 0755 /home/ftuser \
  && chmod -R a+rX /home/ftuser/.local

USER ftuser

ENTRYPOINT ["python", "/usr/local/bin/freqtrade-entrypoint"]
CMD ["trade"]

FROM runtime-image AS platform-operator-image

USER root
RUN apt-get update \
  && apt-get -y install --no-install-recommends git \
  && apt-get clean \
  && rm -rf /var/lib/apt/lists/*

COPY --chown=root:root --chmod=0444 \
  tools/__init__.py \
  tools/committed_git.py \
  tools/runtime_templates.py \
  tools/runtime_artifacts.py \
  tools/runtime_registry_cli.py \
  /opt/platform-operator/tools/

ARG PLATFORM_OPERATOR_ROOT_COMMIT
RUN case "$PLATFORM_OPERATOR_ROOT_COMMIT" in \
      *[!0-9a-f]*) exit 1 ;; \
    esac \
  && case "${#PLATFORM_OPERATOR_ROOT_COMMIT}" in \
      40|64) ;; \
      *) exit 1 ;; \
    esac \
  && install -d -o ftuser -g ftuser -m 0555 \
    /opt/platform-operator/repository \
    /opt/platform-operator/repository/.git \
    /opt/platform-operator/repository/ops \
    /opt/platform-operator/repository/ops/adapter-templates \
    /opt/platform-operator/repository/ops/runtime-policies \
    /opt/platform-operator/repository/ops/config \
    /opt/platform-operator/repository/ft_userdata \
    /opt/platform-operator/repository/ft_userdata/user_data \
    /opt/platform-operator/repository/ft_userdata/user_data/strategies \
  && install -o root -g root -m 0444 /dev/null \
    /opt/platform-operator/repository/ft_userdata/user_data/config.example.json \
  && install -o root -g root -m 0444 /dev/null \
    /opt/platform-operator/repository/ft_userdata/user_data/strategies/sample_strategy.py \
  && install -o root -g root -m 0444 /dev/null \
    /opt/platform-operator/repository/ops/config/trading-safety.json \
  && printf '%s\n' "$PLATFORM_OPERATOR_ROOT_COMMIT" \
    > /opt/platform-operator/root-commit \
  && chown root:root /opt/platform-operator/root-commit \
  && chmod 0444 /opt/platform-operator/root-commit

WORKDIR /opt/platform-operator
USER ftuser
ENTRYPOINT ["python", "-m", "tools.runtime_registry_cli"]
CMD []

FROM runtime-image AS final-runtime-image
