'''
This is where the experiment is run ie. personas are fed in 
extarted data form the ad and a series of questions/survyes are asked/conducted
'''

from client import OpenaiClient

class Experiment(OpenaiClient):
    def __init__(self, prompt: str):
        self.prompt = prompt

