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
    uvicorn.run(create_app(config), host=config.host, port=config.port)


if __name__ == "__main__":
    cli()
