# Copyright 2022, Charles Powell

import logging
import asyncio
from typing import Dict
from asyncio_mqtt import Client, MqttError
from contextlib import AsyncExitStack

from .mqtt_listener import MQTTListener

MQTT_LOGGER = logging.getLogger('mqtt')
MQTT_LOGGER.setLevel(logging.WARNING)


async def cancel_tasks(tasks):
    for task in tasks:
        if task.done():
            continue
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


class MQTTController:
    client = None
    topics: Dict[str, MQTTListener] = None

    def __init__(self, host, port=1883, username=None, password=None):
        self.host = host
        self.port = port
        self.username = username
        self.password = password

        self.data_sources = []
        self.topics = {}

    async def connect(self):
        # Create task
        await self.client_handler()

    async def client_handler(self):
        logging.info(f"Starting MQTT client to URL: {self.host}")
        reconnect_interval = 5  # [seconds]
        while True:
            try:
                await self.listen()
            except MqttError as error:
                logging.error(f'Disconnected from MQTT broker with error: {error}')
                logging.debug(f'MQTT client disconnected/ended, reconnecting in {reconnect_interval}...')
                await asyncio.sleep(reconnect_interval)
            except (KeyboardInterrupt, asyncio.CancelledError):
                return False
            except Exception as error:
                logging.error(f'Stopping MQTT client with error: {error}')
                return False

    async def listen(self):
        async with AsyncExitStack() as stack:
            # Track tasks
            tasks = set()
            stack.push_async_callback(cancel_tasks, tasks)

            # Connect to the MQTT broker
            client = Client(self.host, self.port, username=self.username, password=self.password)
            await stack.enter_async_context(client)

            logging.info(f'MQTT client connected')
            # Add tasks for each data source handler
            for ds in self.data_sources:
                # Get handlers from data source
                ds_listeners = ds.listeners()
                # Iterate through data source listeners and convert to
                # 'prime' listeners for each topic
                for listener in ds_listeners:
                    topic = listener.topic
                    funcs = listener.handlers
                    if topic in self.topics:
                        # Add these handlers to existing top level topic handler
                        logging.debug(f'Adding handlers for existing prime Listener: {topic}')
                        ext_topic = self.topics[topic]
                        ext_topic.handlers.extend(funcs)
                    else:
                        # Add this instance as a new top level handler
                        logging.debug(f'Creating new prime Listener for topic: {topic}')
                        self.topics[topic] = MQTTListener(topic, funcs)

            # Add handlers for each topic as a filtered topic
            for topic, listener in self.topics.items():
                manager = client.filtered_messages(topic)
                messages = await stack.enter_async_context(manager)
                task = asyncio.create_task(self.parse_messages(messages))
                tasks.add(task)

            # Subscribe to all topics
            # Assume QoS 0 for now
            all_topics = [(t, 0) for t in self.topics.keys()]
            logging.info(f'Subscribing to MQTT {len(all_topics)} topic(s)')
            logging.debug(f'Topics: {all_topics}')
            try:
                await client.subscribe(all_topics)
            except ValueError as err:
                logging.error(f'MQTT Subscribe error: {err}')

            # Gather all tasks
            await asyncio.gather(*tasks)
            logging.info(f'Listening for MQTT updates')

    async def parse_messages(self, messages):
        async for message in messages:
            topic = message.topic
            # Get handlers and iterate through
            listener = self.topics[topic]
            for func in listener.handlers:
                # Decode to UTF-8
                await func(message.payload.decode())


if __name__ == "__main__":
    pass
