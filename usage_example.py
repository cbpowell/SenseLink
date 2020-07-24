from SenseLink import *
import asyncio
import logging
import sys
import os
import nest_asyncio
nest_asyncio.apply()

root = logging.getLogger()
root.setLevel(logging.INFO)
handler = logging.StreamHandler(sys.stdout)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
root.addHandler(handler)


async def main():
    # Get environment variables
    document = open('config_private.yaml', 'r')

    # Create controller, with config
    controller = SenseLink(document)

    # Start and run indefinitely
    loop = asyncio.get_event_loop()
    loop.create_task(controller.start())
    loop.run_forever()


if __name__ == "__main__":
    asyncio.run(main())




