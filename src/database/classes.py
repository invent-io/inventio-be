from abc import abstractmethod

from bson import ObjectId

from database.mongo_helper import MongoHelper, DuplicatedItemException


class MissingAttributeException(Exception):
    def __init__(self, attribute):
        self.attribute = attribute
        message = "Attribute %s is required, but not present in request" % attribute
        super().__init__(message)


DELETED_FIELD = "__deleted"


class DatabaseClassObj:
    @property
    @abstractmethod
    def collection_name(self):
        pass

    @property
    @abstractmethod
    def fields(self):
        pass

    @property
    @abstractmethod
    def required_fields(self):
        pass

    @property
    @abstractmethod
    def unique_fields(self):
        pass

    @property
    @abstractmethod
    def search_fields(self):
        pass

    @property
    @abstractmethod
    def id_field(self):
        pass

    default_fields = ["_id", DELETED_FIELD]

    def __fields__(self):
        return self.default_fields + self.fields

    def __init__(self, mongo_helper: MongoHelper, _id = None):
        self.mongo_helper = mongo_helper
        if _id is not None:
            obj = self.mongo_helper.db[self.collection_name].find_one({self.id_field: _id,
                                                                       DELETED_FIELD: {"$exists": False}})
            if not obj:
                raise ValueError("Object with %s = %s in collection %s not found" % (self.id_field, _id, self.collection_name))

    def __getitem__(self, item):
        if item in self.__fields__():
            return self.__getattribute__(item)
        else:
            raise AttributeError()

    def __setitem__(self, key, value):
        if key in self.__fields__():
            return self.__setattr__(key, value)
        else:
            raise AttributeError()

    def __contains__(self, item):
        return hasattr(self, item)

    def __iter__(self):
        for field in self.__fields__():
            if field in self:
                if field == "_id":
                    yield field, str(self[field])
                else:
                    yield field, self[field]

    def mongo_update_dict(self):
        return {"$set": {k: v for k, v in dict(self).items() if k != "_id"}}

    def create_from_request(self, request):
        for field in self.__fields__():
            if request.json.get(field) is not None:
                setattr(self, field, request.json.get(field))

        for field in self.required_fields:
            if request.json.get(field) is None:
                raise MissingAttributeException(field)

        for field in self.unique_fields:
            if self.mongo_helper.db[self.collection_name].find_one({field: self[field], DELETED_FIELD: True}):
                raise DuplicatedItemException(request)

        if self["_id"]:
            raise TypeError("Unable to create item, _id attribute already set")

        inserted = self.mongo_helper.db[self.collection_name].insert_one(dict(self))
        self["_id"] = inserted.inserted_id
        return self

    def _create_from_mongo_entry(self, entry):
        for k, v in entry.values():
            self.__setattr__(k, v)
        return self

    def update_in_db(self):
        if "_id" not in self and self.id_field not in self:
            raise MissingAttributeException("_id")

        if "_id" in self:
            self.mongo_helper.db[self.collection_name].update_one({"_id": ObjectId(self["_id"])},
                                                                  self.mongo_update_dict())
        else:
            self.mongo_helper.db[self.collection_name].update_one({self.id_field, self[self.id_field]},
                                                                  self.mongo_update_dict())

    def update_from_request(self, request):
        if "_id" not in self and self.id_field not in self:
            raise MissingAttributeException("_id")

        if "_id" in self:
            self.mongo_helper.db[self.collection_name].update_one({"_id": ObjectId(self["_id"])},
                                                                  {"$set": request})
        else:
            self.mongo_helper.db[self.collection_name].update_one({self.id_field, self[self.id_field]},
                                                                  {"$set": request})

    def delete(self):
        if "_id" not in self and self.id_field not in self:
            raise MissingAttributeException("_id")

        if "_id" in self:
            self.mongo_helper.db[self.collection_name].update_one({"_id": ObjectId(self["_id"])},
                                                                  {"$set": {DELETED_FIELD: True}})
        else:
            self.mongo_helper.db[self.collection_name].update_one({self.id_field, self[self.id_field]},
                                                                  {"$set": {DELETED_FIELD: True}})

    def search(self, query_regex):
        return list(self.mongo_helper.db[self.collection_name].find(
            {'$and': [
                {DELETED_FIELD: {"$exists": False}},
                {"$or": [
                    {field: {'$regex': query_regex}}
                    for field in self.search_fields
                ]}
            ]}
           ))

    def get_all(self):
        return list(self.mongo_helper.db[self.collection_name].find(
            {DELETED_FIELD: {"$exists": False}}
        ))

    def count(self):
        return self.mongo_helper.db[self.collection_name].find({DELETED_FIELD: {"$exists": False}}).count()


class Item(DatabaseClassObj):
    collection_name = "item"
    fields = ["description", "name", "tags",
              "default_storage_location", "location_blacklist",
              "location_whitelist", "item_id"]
    id_field = "item_id"
    unique_fields = ["item_id", "tags"]
    required_fields = ["name", "item_id", "tags"]
    search_fields = ["name", "item_id", "description", "tags"]


class Sensor(DatabaseClassObj):
    collection_name = "sensor"
    fields = ["description", "name", "sensor_id",
              "tag", "types"]
    id_field = "sensor_id"
    unique_fields = ["sensor_id"]
    required_fields = ["name", "sensor_id"]
    search_fields = ["name", "sensor_id", "description", "tag"]


class Event(DatabaseClassObj):
    collection_name = "event"
    fields = ["received_timestamp", "event_timestamp", "event_details",
              "sensor_id", "item_id", "tag_id"]
    id_field = "event_timestamp"
    unique_fields = ["event_timestamp"]
    required_fields = ["received_timestamp", "event_timestamp", "event_details",
                       "sensor_id", "tag_id"]
    search_fields = ["event_details", "sensor_id", "item_id", "tag_id"]

    def filter(self, sensor_id, item_id, start_timestamp_range, end_timestamp_range):
        filters = []
        if sensor_id is not None:
            if isinstance(sensor_id, list):
                filters.append({'sensor_id': {"$in": sensor_id}})
            else:
                filters.append({'sensor_id': sensor_id})

        if item_id is not None:
            if isinstance(item_id, list):
                filters.append({'item_id': {"$in": item_id}})
            else:
                filters.append({'item_id': item_id})

        if start_timestamp_range is not None and end_timestamp_range is not None:
            filters.append({'event_timestamp': {"$gte": start_timestamp_range, "$lte": end_timestamp_range}})

        return list(self.mongo_helper.db[self.collection_name].find(filters))