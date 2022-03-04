from SenseLink import *
import logging
import sys
import random

root = logging.getLogger()
root.setLevel(logging.DEBUG)
handler = logging.StreamHandler(sys.stdout)


async def change_mutable_plug_power(plug):
    while True:
        power = random.randrange(2, 15, 1)
        plug.data_source.power = power
        logging.info(f"Changed power to {power}")
        await asyncio.sleep(random.randrange(1, 4, 1))


async def main():
    # Get config
    config = open('your_config_file.yml', 'r')
    # Create controller, with config
    controller = SenseLink(config)
    # Create instances
    controller.create_instances()

    # Get Mutable controller object, and create task to update it
    mutable_plug = controller.plug_for_mac("50:c7:bf:f6:4f:39")
    plug_update = change_mutable_plug_power(mutable_plug)

    # Get SenseLink tasks to add these
    tasks = controller.tasks
    tasks.add(plug_update)
    tasks.add(controller.server_start())

    logging.info("Starting SenseLink controller")
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
