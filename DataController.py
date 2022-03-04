# Copyright 2020, Charles Powell

import websockets
import json
import logging
import asyncio
import dpath.util
from socket import gaierror
from asyncio_mqtt import Client, MqttError
from contextlib import AsyncExitStack
from typing import Dict

# Independently set WS logger
wslogger = logging.getLogger('websockets')
wslogger.setLevel(logging.WARNING)

MQTT_LOGGER = logging.getLogger('mqtt')
MQTT_LOGGER.setLevel(logging.WARNING)


def safekey(d, keypath, default=None):
    try:
        val = dpath.util.get(d, keypath)
        return val
    except KeyError:
        return default


class HASSController:
    ws = None
    event_rq_id = 1
    bulk_rq_id = 2
    data_sources = []

    def __init__(self, url, auth_token):
        self.url = url
        self.auth_token = auth_token

    async def connect(self):
        # Create task
        await self.client_handler()

    async def client_handler(self):
        logging.info(f"Starting websocket client to URL: {self.url}")
        try:
            async with websockets.connect(self.url) as websocket:
                self.ws = websocket
                # Wait for incoming message from server
                while True:
                    try:
                        message = await websocket.recv()
                        logging.debug(f"Received message: {message}")
                        await self.on_message(websocket, message)
                    except websockets.exceptions.ConnectionClosed as err:
                        logging.error(f"Lost connection to websocket server ({err})")
                        logging.info(f"Reconnecting in 10...")
                        await asyncio.sleep(10)
                        asyncio.create_task(self.client_handler())
                        return False
        except (websockets.exceptions.WebSocketException, asyncio.exceptions.TimeoutError, gaierror) as err:
            logging.error(f"Unable to connect to server at {self.url} ({type(err)}:{err})")
            logging.info(f"Attempting to reconnect in 10...")
            await asyncio.sleep(10)
            asyncio.create_task(self.client_handler())

    async def on_message(self, ws, message):
        # Authentication with HASS Websockets
        message = json.loads(message)

        if 'type' in message and message['type'] == 'auth_required':
            logging.info("Authentication requested")
            auth_response = {'type': 'auth', 'access_token': self.auth_token}
            await ws.send(json.dumps(auth_response))

        elif 'type' in message and message['type'] == "auth_invalid":
            logging.error("Authentication failed")

        elif 'type' in message and message['type'] == "auth_ok":
            logging.info("Authentication successful")
            # Authentication successful
            # Send subscription command
            events_command = {
                "id": self.event_rq_id,
                "type": "subscribe_events",
                "event_type": "state_changed"
            }
            await ws.send(json.dumps(events_command))
            logging.info("Event update request sent")

            # Request full status update to get current value
            events_command = {
                "id": self.bulk_rq_id,
                "type": "get_states",
            }
            await ws.send(json.dumps(events_command))
            logging.info("All states request sent")

        elif 'type' in message and message['id'] == self.event_rq_id:
            # Look for state_changed events
            logging.debug("Potential event update received")
            # Check for data
            if not safekey(message, 'event/data'):
                return
            # Notify attached data sources
            for ds in self.data_sources:
                ds.parse_incremental_update(message['event']['data'])

        elif 'type' in message and message['id'] == self.bulk_rq_id:
            # Look for state_changed events
            logging.info("Bulk update received")
            if message.get('result') is None:
                return
            # Extract data
            bulk_update = message.get('result')
            logging.debug(f"Entity update received: {bulk_update}")
            # Loop through statuses
            for status in bulk_update:
                # Notify attached data sources
                for ds in self.data_sources:
                    ds.parse_bulk_update(status)
        else:
            logging.debug(f"Unknown/unhandled message received: {message}")


class MQTTListener:
    def __init__(self, topic, hndls=None):
        self.topic = topic
        self.handlers = []
        self.handlers.extend(hndls)


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
