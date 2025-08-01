FROM ubuntu:22.04
LABEL authors="jcoller"

RUN apt-get update && apt-get install -y \
    curl jq git sudo unzip libcurl4 openssh-client ca-certificates && \
    apt-get clean

RUN useradd -m runner && echo "runner ALL=NOPASSWD: ALL" >> /etc/sudoers

WORKDIR /home/runner

ARG RUNNER_VERSION=2.316.0
RUN curl -L -o actions-runner.tar.gz https://github.com/actions/runner/releases/download/v${RUNNER_VERSION}/actions-runner-linux-x64-${RUNNER_VERSION}.tar.gz && \
    tar xzf actions-runner.tar.gz && \
    rm actions-runner.tar.gz && \
    ./bin/installdependencies.sh

COPY entrypoint.sh .

RUN chmod +x entrypoint.sh

USER runner
ENTRYPOINT ["./entrypoint.sh"]
