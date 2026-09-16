import openai
import time
import json
class Get:
    def __init__(self):
        self.prompt = ""
    def calc(self, query, temp=1, n=1, model='4omini'):
        '''
        Please implement this function to call your API model.

        **Input:**
        - `query`: string

        **Output:**
        - `[{{output string}}]`
        - `{'prompt': {{prompt cost, float}}, 'completion': {{completion cost, float}}}`

        '''


