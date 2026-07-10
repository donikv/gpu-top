"""gpu-top agent: samples local GPUs and pushes batches to the central server.

Zero third-party dependencies (stdlib urllib). Samples are buffered in a
bounded deque while the server is unreachable and flushed as one batch on
reconnect, so short outages leave no gap in the dashboard charts.
"""
import argparse
import json
import logging
import time
import urllib.error
import urllib.request
from collections import deque

log = logging.getLogger("gpu_top.agent")

BUFFER_MAXLEN = 720          # ~1h of backlog at the 5s default interval
HTTP_TIMEOUT = 10.0
LOG_EVERY = 60.0             # rate-limit repeated failure logs to once a minute


def push(url, token, server_name, samples):
    from .. import __version__
    body = json.dumps({
        "server": server_name,
        "agent_version": __version__,
        "samples": list(samples),
    }).encode()
    req = urllib.request.Request(
        f"{url}/api/ingest", data=body, method="POST",
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT):
        pass


def run(config):
    from ..collector import ContainerResolver, collect_snapshot

    resolver = ContainerResolver()
    buffer = deque(maxlen=BUFFER_MAXLEN)
    last_err_log = 0.0

    log.info("pushing to %s as %r every %gs", config.url, config.server_name,
             config.interval)
    while True:
        started = time.monotonic()
        try:
            sample = collect_snapshot(resolver)
            if sample["gpus"]:
                buffer.append(sample)
            else:
                log.warning("nvidia-smi returned no GPUs; skipping sample")
        except Exception:
            log.exception("collection failed; skipping sample")

        if buffer:
            try:
                push(config.url, config.token, config.server_name, buffer)
                buffer.clear()
                last_err_log = 0.0
            except urllib.error.HTTPError as e:
                if e.code == 401:
                    log.error("server rejected our token (401) - check [agent].token "
                              "against the server's [agents].tokens; retrying anyway")
                elif time.monotonic() - last_err_log > LOG_EVERY:
                    log.warning("push failed (HTTP %d); buffering %d samples",
                                e.code, len(buffer))
                    last_err_log = time.monotonic()
            except OSError as e:
                if time.monotonic() - last_err_log > LOG_EVERY:
                    log.warning("server unreachable (%s); buffering %d samples",
                                e, len(buffer))
                    last_err_log = time.monotonic()

        time.sleep(max(0.0, config.interval - (time.monotonic() - started)))


def cli():
    parser = argparse.ArgumentParser(
        prog="gpu-top-agent",
        description="Collect local GPU metrics and push them to a gpu-top server.")
    parser.add_argument("-c", "--config", default="/etc/gpu-top/agent.toml",
                        help="path to agent.toml (default: %(default)s)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")

    from ..config import load_agent_config
    try:
        run(load_agent_config(args.config))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    cli()
