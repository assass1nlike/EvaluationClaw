import logging

from runners.cli.autocontrol import main

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
main()
