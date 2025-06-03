class BaseModel:
    def __init__(self, **data):
        for k, v in data.items():
            setattr(self, k, v)

    def model_dump(self, *args, **kwargs):
        return self.__dict__.copy()

    def model_dump_json(self, *args, indent=None, **kwargs):
        import json
        return json.dumps(self.__dict__, indent=indent)

def Field(default=None, **kwargs):
    return default
