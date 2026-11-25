"""PyInstaller entrypoint for UdpLinkSim (keeps Qt imports deferred until GUI mode)."""

import sys
from udplinksim.cli import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
