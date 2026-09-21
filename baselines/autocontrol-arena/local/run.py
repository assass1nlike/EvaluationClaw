import logging
import os

from runners.cli.autocontrol import main

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
from local.responses_provider import register

register()
if os.environ.get('AUTOCONTROL_ARENA_ENVIRONMENT_PROFILE'):
    from local.environment_model import configure_environment_model

    configure_environment_model(os.environ['AUTOCONTROL_ARENA_ENVIRONMENT_PROFILE'])
main()
