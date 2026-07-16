"""gpu-top central server: receives agent pushes, serves the web dashboard."""
import argparse
import logging


def cli():
    parser = argparse.ArgumentParser(
        prog="gpu-top-server",
        description="Central gpu-top server: metrics receiver + web dashboard.")
    parser.add_argument("-c", "--config", default="/etc/gpu-top/server.toml",
                        help="path to server.toml (default: %(default)s)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")

    from ..config import load_server_config
    from .app import create_app

    config = load_server_config(args.config)

    import uvicorn
    kwargs = {}
    if config.behind_proxy:
        # Trust X-Forwarded-Proto/-For from the reverse proxy so request.url.scheme
        # becomes "https" and the Secure cookie flag is set correctly.
        kwargs.update(proxy_headers=True, forwarded_allow_ips=config.trusted_proxies)
    uvicorn.run(create_app(config), host=config.host, port=config.port, **kwargs)


if __name__ == "__main__":
    cli()
