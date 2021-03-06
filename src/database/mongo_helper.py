import json

import pymongo.database
import pymongo
from bson import json_util
from datetime import datetime


class DuplicatedEventReceived(Exception):
    def __init__(self, item_id, message="Received event is already in database"):
        self.item_id = item_id
        super().__init__(message)


class DuplicatedItemException(Exception):
    def __init__(self, event, message="Item is already in database"):
        self.event = event
        super().__init__(message)


class MongoHelper:
    @classmethod
    def init_from_config(cls, config):
        return MongoHelper(
            host=config.get("mongodb", "host"),
            port=int(config.get("mongodb", "port")),
            username=config.get("mongodb", "username"),
            password=config.get("mongodb", "password"),
            auth_source=config.get("mongodb", "auth_source"),
            database=config.get("mongodb", "database"),
        )

    def __init__(self, host, port, username, password, auth_source, database):
        self.db = pymongo.MongoClient(host=host,
                                      port=port,
                                      username=username,
                                      password=password,
                                      authSource=auth_source)[database]

    def get_event_count(self):
        return self.db["event"].find({}).count()

    def get_sensor(self, sensor_id):
        return self.db['sensor'].find_one({"sensor_id": sensor_id})

    def get_item_by_tag(self, tag_id):
        return self.db['item'].find_one({"tags": tag_id})

    def add_event(self, sensor_id, tag_id, item_id, event_timestamp, event_details, alert=None):
        event = {
            'inserted_timestamp': datetime.now().timestamp(),
            'event_timestamp': event_timestamp,
            'event_details': event_details,
            'sensor_id': sensor_id,
            'item_id': item_id,
            'tag_id': tag_id
        }
        if alert:
            event["alert"] = alert
        if not self.db["event"].find_one({"event_timestamp": event_timestamp}):
            return self.db["event"].insert_one(event)
        else:
            raise DuplicatedEventReceived(event)

    def add_sensor(self, payload):
        response = self.get_item(payload['sensor_id'])
        if response: return 'Sensor already exists!'
        return self.db['sensor'].insert_one(payload)

    def get_sensor_by_name(self, name):
        return json_util.dumps(self.db['sensor'].find_one({'sensor_name': name}))

    def add_item(self, payload):
        response = self.get_item(payload['item_id'])
        if response:
            raise DuplicatedItemException(payload['item_id'])
        return self.db['item'].insert_one(payload)

    def get_item(self, item_id):
        return self.db['item'].find_one({'item_id': item_id})

    def check_token_ttl(self):
        if self.db['token'].indexes.find_one({'name': 'token_expiration_ttl'}):
            return False
        self.db['token'].create_index(
            {"last_modified": 1},
            {'expireAfterSeconds': 24*60*60})
        return True

    def add_access_token(self):
        self.check_token_ttl()

    def update_access_token(self):
        self.db
