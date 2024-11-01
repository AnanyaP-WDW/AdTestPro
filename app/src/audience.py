'''
This is where 3 personas are created from the taget audience form
''' 

from .client import OpenaiClient
from .models import TargetAudienceForm
import openai
import os
from .utils import read_prompt_file, add_variable_to_prompt, PromptFile

# use tneacity for retyr mehcanism and json output checks

class CreateSyntheticAgents(OpenaiClient):
    '''
    Each agent corresponds to each persona
    '''
    def __init__(self, target_audience_form: TargetAudienceForm, api_key: str):
        super().__init__(api_key=os.getenv("OPENAI_API_KEY"))
        self.target_audience_form = target_audience_form

    async def generate_response(self, prompt_file: PromptFile = PromptFile.CREATE_TARGET_AUDIENCE, temp: float = 0.0):
        try:
            try:
                prompt_content = await read_prompt_file(prompt_file.value)
                self.log_info(f"Prompt file found: create_target_audience.txt")
                prompt_content = await add_variable_to_prompt(prompt_content, "target_audience", self.target_audience_form.to_json())
            except FileNotFoundError as e:
                self.log_error(f"Prompt file not found: {e}")
                raise Exception(f"Prompt file not found: {e}")
            
            response = await self.aclient.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {
                        "role": "system",
                        "content": """You are an AI assistant specializing in marketing, consumer behavior, and market research. Your task is to generate three diverse target audience personas from the given TARGET AUDIENCE FORM. specifically designed for synthetic ad creative testing and focus group participation. Each persona should be a vivid, realistic individual who can provide valuable insights in a focus group setting""",
                    },
                    {
                        "role": "user",
                        "content": prompt_content
                    }
                ],
                temperature=temp,
                max_tokens=3000,
                response_format={"type": "json_object"}
                )

            return response.choices[0].message.content
        
        except openai.APIError as e:
            raise Exception(f"OpenAI API returned an API Error: {e}")

        except openai.APIConnectionError as e:
            raise Exception(f"Failed to connect to OpenAI API: {e}")

        except openai.RateLimitError as e:
            raise Exception(f"OpenAI API request exceeded rate limit: {e}")

