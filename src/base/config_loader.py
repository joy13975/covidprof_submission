# Class that loads parameters into class attributes
import json


class ConfigLoader:
    def __init__(self, *args, config_file=None, **kwargs):
        '''Constructor'''
        self.load_config(config_file)

    def load_config(self, config_file):
        '''Load JSON configuration into class attributes'''
        if config_file is None:
            cls_name = self.__class__.__name__.lower()
            config_file = f'config/{cls_name}.json'
        with open(config_file, 'r') as f:
            config = json.load(f)
        for k, v in config.items():
            setattr(self, k, v)
