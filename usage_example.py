from TPLinkController import *
import asyncio
import logging
import sys
import os
import nest_asyncio
nest_asyncio.apply()

root = logging.getLogger()
root.setLevel(logging.DEBUG)
handler = logging.StreamHandler(sys.stdout)
handler.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
root.addHandler(handler)


async def main():
    # Get environment variables
    document = open('config.yaml', 'r')

    # Create controller, with config
    controller = TPLinkController(document)

    # Start and run indefinitely
    loop = asyncio.get_event_loop()
    loop.create_task(controller.start())
    loop.run_forever()


if __name__ == "__main__":
    asyncio.run(main())




