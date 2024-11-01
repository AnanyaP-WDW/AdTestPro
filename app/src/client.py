



from openai import AsyncOpenAI
import logging

class OpenaiClient:
    '''
    Base class for all OpenAI clients
    children classes should implement the generate_response and call_openai_api methods
    children classes:
    - audience.py -> CreateSyntheticAgents
    - extract.py -> ExtractAdData
    - analyze.py -> FocusGroupAnalysis
    '''
    def __init__(self, api_key: str):
        self.aclient = AsyncOpenAI(api_key=api_key)
        self.logger = logging.getLogger(__name__)
        self.setup_logging()
    #this needs to be overriden by classes that inherit openaiclient
    async def generate_response(self, **kwargs) -> str:
        raise NotImplementedError("This method needs to be overridden by subclasses")
    #this needs to be overriden by classes that inherit openaiclient
    async def call_openai_api(self, **kwargs) -> str:
        raise NotImplementedError("This method needs to be overridden by subclasses")
    
    def setup_logging(self):
        self.logger.setLevel(logging.DEBUG)

        # Create a console handler and set level to debug
        ch = logging.StreamHandler()
        ch.setLevel(logging.DEBUG)

        # Create a formatter
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

        # Add formatter to ch
        ch.setFormatter(formatter)

        # Add ch to logger
        self.logger.addHandler(ch)

    def log_info(self, message: str):
        self.logger.info(message)

    def log_debug(self, message: str):
        self.logger.debug(message)

    def log_error(self, message: str):
        self.logger.error(message)
