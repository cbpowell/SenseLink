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
    # Get environment variables
    document = open('config.yml', 'r')

    # Create controller, with config
    controller = SenseLink(document)

    # Start and run indefinitely
    loop = asyncio.get_event_loop()
    loop.create_task(controller.start())
    loop.run_forever()


if __name__ == "__main__":
    asyncio.run(main())




