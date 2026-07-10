"""gpu-top: htop-style GPU monitor with docker container attribution.

The package is split into:
  collector  -- shared nvidia-smi/docker data layer (no curses)
  tui        -- the original curses interface (`gpu-top`)
  agent      -- pushes metrics to a central server (`gpu-top-agent`)
  server     -- FastAPI receiver + web dashboard (`gpu-top-server`)
"""
__version__ = "0.2.0"

# Re-exports for backward compatibility: the `gpu-top` console script points at
# gpu_top:cli, and older code may import the data helpers from the package root.
from .collector import (  # noqa: F401
    GPU_FIELDS, PROC_FIELDS, CID_RE, HOME_RE,
    ContainerResolver, cmdline, collect_snapshot, get_gpus, get_processes,
    get_uuid_map, proc_name, run_query, safe_float, username,
)
from .tui import cli, main  # noqa: F401
