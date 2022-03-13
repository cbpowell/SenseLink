import logging
import asyncio
import os
import argparse
from senselink import SenseLink

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-c", "--config", help="specify config file path")
    parser.add_argument("-l", "--log", help="specify log level (DEBUG, INFO, etc)")
    parser.add_argument("-q", "--quiet", help="do not respond to Sense UPD queries", action="store_true")
    args = parser.parse_args()
    config_path = args.config or '/etc/senselink/config.yml'
    loglevel = args.log or 'WARNING'

    loglevel = os.environ.get('LOGLEVEL', loglevel).upper()
    logging.basicConfig(level=loglevel)

    # Assume config file is in etc directory
    config_location = os.environ.get('CONFIG_LOCATION', config_path)
    logging.debug(f"Using config at: {config_location}")
    config = open(config_location, 'r')

    server = SenseLink(config)

    if os.environ.get('SENSE_RESPONSE', 'True').upper() == 'TRUE' and not args.quiet:
        logging.info("Will respond to Sense broadcasts")
        server.should_respond = True
    # Create instances
    server.create_instances()

    # Start and run indefinitely
    logging.info("Starting SenseLink controller")
    try:
        asyncio.run(server.start())
    except KeyboardInterrupt:
        logging.info("Interrupt received, stopping SenseLink")
