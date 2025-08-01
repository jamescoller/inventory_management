FROM ubuntu:22.04
LABEL authors="jcoller"

# Install base dependencies
RUN apt-get update && apt-get install -y \
    curl jq git sudo unzip libcurl4 openssh-client ca-certificates gnupg lsb-release \
    && apt-get clean

# Install Docker
RUN curl -fsSL https://get.docker.com | bash

# Install Docker Compose CLI (v2)
RUN curl -L "https://github.com/docker/compose/releases/download/v2.24.5/docker-compose-$(uname -s)-$(uname -m)" \
    -o /usr/local/bin/docker-compose \
    && chmod +x /usr/local/bin/docker-compose

# Create non-root user
RUN useradd -m runner && echo "runner ALL=NOPASSWD: ALL" >> /etc/sudoers

WORKDIR /home/runner

# Install GitHub runner
ARG RUNNER_VERSION=2.327.1
RUN curl -L -o actions-runner.tar.gz https://github.com/actions/runner/releases/download/v${RUNNER_VERSION}/actions-runner-linux-x64-${RUNNER_VERSION}.tar.gz \
    && tar xzf actions-runner.tar.gz \
    && rm actions-runner.tar.gz \
    && ./bin/installdependencies.sh

COPY entrypoint.sh .
RUN chmod +x entrypoint.sh

USER runner
ENTRYPOINT ["./entrypoint.sh"]
