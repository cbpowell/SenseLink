from SenseLink import *
import logging
import sys

root = logging.getLogger()
root.setLevel(logging.DEBUG)
handler = logging.StreamHandler(sys.stdout)


def main():
    # Get config
    config = open('config_private.yml', 'r')
    # Create controller, with config
    controller = SenseLink(config)
    # Start and run indefinitely
    logging.info("Starting SenseLink controller")
    loop = asyncio.get_event_loop()
    tasks = asyncio.gather(*[controller.start()])
    loop.run_until_complete(tasks)


if __name__ == "__main__":
    asyncio.run(main())
