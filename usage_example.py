from SenseLink import *
import asyncio
import logging
import sys
import nest_asyncio
nest_asyncio.apply()

root = logging.getLogger()
root.setLevel(logging.DEBUG)
handler = logging.StreamHandler(sys.stdout)


async def main():
    # Get config
    config = open('config_example.yml', 'r')
    # Create controller, with config
    controller = SenseLink(config)
    # Start and run indefinitely
    loop = asyncio.get_event_loop()
    loop.create_task(controller.start())
    loop.run_forever()


if __name__ == "__main__":
    asyncio.run(main())




