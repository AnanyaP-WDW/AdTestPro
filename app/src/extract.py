'''
This is where all the data from an ad is extracted
'''
#TODO:
# - add logging to all classes
# - add error handling to all classes
# - generate_response needs to be implemented 


from .client import OpenaiClient
import openai
from typing import Dict, Any
from .utils import read_prompt_file
import base64
import mimetypes
import aiofiles
from enum import Enum
import asyncio
from .utils import PromptFile
# use tneacity for retry mehcanism and json output checks




class ExtractImageAdData(OpenaiClient):
    def __init__(self, image_path: str, api_key: str):
        super().__init__(api_key=api_key)
        self.image_path = image_path

    async def get_base64_image(self, image_path: str):
        try:
            async with aiofiles.open(image_path, mode='rb') as f:
                image_data = await f.read()
            self.log_info("Image read successfully")
        except:
            self.log_error("Failed to read image:")
            raise Exception("Failed to read image")
        try:
            base64_image = base64.b64encode(image_data).decode('utf-8')
            self.log_info("Image encoded to base64 successfully")
        except:
            self.log_error("Failed to encode image to base64")
            raise Exception("Failed to encode image to base64")
        try:
            mime_type,_ = mimetypes.guess_type(image_path)
            image_url = f"data:{mime_type};base64,{base64_image}"
            self.log_info("Image URL created successfully")
            return image_url
        except:
            self.log_error("Failed to create image URL")
            raise Exception("Failed to create image URL")
    
    async def call_openai_api(self, prompt_file: PromptFile, temp: float = 0.0):
        try:
            try:
                prompt_content = await read_prompt_file(prompt_file.value)
                self.log_info(f"Prompt file found: {prompt_file.value}")
            except FileNotFoundError as e:
                self.log_error(f"Prompt file not found: {e}")
                raise Exception(f"Prompt file not found: {e}")
            
            image_url = await self.get_base64_image(self.image_path)
            
            response = await self.aclient.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {
                        "role": "system",
                        "content": """You are an expert at analyzing image ads. I want you to extract the following visual and textual elements from the image ad I provide.""",
                    },
                    {
                        "role": "user",
                        "content":[
                        {
                            "type": "text",
                            "text":prompt_content   
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": image_url
                            }
                        }
                        ]
                    }
                ],
                temperature=temp,
                max_tokens=2000,
                response_format={"type": "json_object"}
                )

            return response.choices[0].message.content
        
        except openai.APIError as e:
            self.log_error(f"OpenAI API returned an API Error: {e}")
            raise Exception(f"OpenAI API returned an API Error: {e}")

        except openai.APIConnectionError as e:
            self.log_error(f"OpenAI API returned an API Error: {e}")
            raise Exception(f"Failed to connect to OpenAI API: {e}")

        except openai.RateLimitError as e:
            self.log_error(f"OpenAI API returned an API Error: {e}")
            raise Exception(f"OpenAI API request exceeded rate limit: {e}")
        
    async def generate_response(self):
        # code to extract visual elements, text_tone, engagement elements at once

        try:
            tasks = [self.call_openai_api(prompt_file=PromptFile.EXTRACT_VISUAL_ELEMENTS),
                     self.call_openai_api(prompt_file=PromptFile.EXTRACT_TEXT_TONE),
                     self.call_openai_api(prompt_file=PromptFile.EXTRACT_ENGAGEMENT_ELEMENTS)
                     ]  

            # Run tasks concurrently
            responses = await asyncio.gather(*tasks)
            return responses
        except Exception as e:
            self.log_error(f"An error occurred while generating responses: {e}")
            raise Exception(f"An error occurred while generating responses: {e}")