import os
import aiofiles
from enum import Enum

PROMPTS_DIR = os.path.join(os.path.dirname(__file__), 'prompts')

class PromptFile(Enum):
    EXTRACT_VISUAL_ELEMENTS = "extract_visual_elements.txt"
    EXTRACT_TEXT_TONE = "extract_text_tone.txt"
    CREATE_TARGET_AUDIENCE = "create_target_audience.txt"
    EXTRACT_ENGAGEMENT_ELEMENTS = "extract_engagement_elements.txt"
    ANALYZE_FOCUS_GROUP = "analyze_focus_group.txt"
    PERSONA_RESPONSE = "persona_response.txt"

async def read_prompt_file(filename: str) -> str:
    """
    Reads the content of a prompt file from the prompts directory.
    
    :param filename: The name of the prompt file.
    :return: The content of the file as a string.
    """
    prompt_file_path = os.path.join(PROMPTS_DIR, filename)
    try:
        async with aiofiles.open(prompt_file_path, 'r') as file:
            return await file.read()
    except FileNotFoundError:
        raise Exception(f"Prompt file not found: {prompt_file_path}")
    except IOError as e:
        raise Exception(f"Error reading prompt file: {e}")

async def add_variable_to_prompt(prompt: str, variable: str, value: str) -> str:
    """
    Adds a variable to a prompt. If the value is a dictionary, it converts it to a string.
    
    :param prompt: The prompt to add the variable to.
    :param variable: The variable to add.
    :param value: The value of the variable.
    :return: The prompt with the variable added.
    """
    try:
        if isinstance(value, dict):
            value = str(value)
        return prompt.replace(f"{{{variable}}}", value)
    except Exception as e:
        raise Exception(f"Error adding variable to prompt: {e}")
