import json


def dict_to_variables(obj, file_path: str):
    with open(file_path) as f:
        _dict = json.load(f)
        setattr(obj, 'json', _dict)

        for k, v in _dict.items():
            setattr(obj, k, v)


class Resource:
    def __init__(self, file_path: str):
        dict_to_variables(self, file_path)


class Strings(Resource):
    def __init__(self):
        super().__init__('resources/strings.json')


class Emotes(Resource):
    def __init__(self):
        super().__init__('resources/emotes.json')


class Links(Resource):
    def __init__(self):
        super().__init__('resources/links.json')


class Images(Resource):
    def __init__(self):
        super().__init__('resources/images.json')


images = Images()
links = Links()
strings = Strings()
emotes = Emotes()
