# Copyright 2022 Charles Powell

class MQTTListener:
    def __init__(self, topic, hndls=None):
        self.topic = topic
        self.handlers = []
        self.handlers.extend(hndls)
