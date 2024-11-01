from .client import OpenaiClient
import openai
from .utils import read_prompt_file, add_variable_to_prompt, PromptFile
import os
from typing import Dict, Any, List
from enum import Enum


class SurveyQuestionEnum(Enum):
    ACTION = 0
    EMOTIONS = 1
    TARGET_DEMOGRAPHIC = 2
    CALL_TO_ACTION = 3
    TONE_AND_STYLE = 4
    POSITIVES = 5
    NEGATIVES = 6
    IMPROVEMENTS = 7
    ENGAGEMENT_SCORE = 8
    APPEAL_SCORE = 9
    BELIEVABILITY_SCORE = 10
    RELEVANCE_SCORE = 11
    TRUSTWORTHY_SCORE = 12
    BRAND_RECALL_SCORE = 13


class SurveyQuestions:
    '''
    Choose 3 questions from a dropdown of 14 questions that are relevant to the ad and target audience  
    '''
    def __init__(self):
        self.questions = [
            "What action is the viewer encouraged to take?",
            "What emotions does the ad evoke?",
            "What elements suggest the target demographic?",
            "Is the call-to-action prominent and compelling?",
            "What is the tone and style of the ad?",
            "What are the positives about this ad creative?",
            "What are the negatives about this ad creative?",
            "What suggestions do you have for improvement?",
            "How engaging do you find this ad creative? Please provide a score between 1 and 10.",
            "How appealing does this ad creative feel? Please provide a score between 1 and 10.",
            "How believable does this ad creative feel? Please provide a score between 1 and 10.",
            "How relevant does this ad creative feel? Please provide a score between 1 and 10.",
            "How trustworthy does this ad creative feel? Please provide a score between 1 and 10.",
            "How is the Brand recall of this ad creative? Please provide a score between 1 and 10."
        ]
        self.selected_questions = []
        self.question_map = {
            SurveyQuestionEnum.ACTION: self.questions[0],
            SurveyQuestionEnum.EMOTIONS: self.questions[1],
            SurveyQuestionEnum.TARGET_DEMOGRAPHIC: self.questions[2],
            SurveyQuestionEnum.CALL_TO_ACTION: self.questions[3],
            SurveyQuestionEnum.TONE_AND_STYLE: self.questions[4],
            SurveyQuestionEnum.POSITIVES: self.questions[5],
            SurveyQuestionEnum.NEGATIVES: self.questions[6],
            SurveyQuestionEnum.IMPROVEMENTS: self.questions[7],
            SurveyQuestionEnum.ENGAGEMENT_SCORE: self.questions[8],
            SurveyQuestionEnum.APPEAL_SCORE: self.questions[9],
            SurveyQuestionEnum.BELIEVABILITY_SCORE: self.questions[10],
            SurveyQuestionEnum.RELEVANCE_SCORE: self.questions[11],
            SurveyQuestionEnum.TRUSTWORTHY_SCORE: self.questions[12],
            SurveyQuestionEnum.BRAND_RECALL_SCORE: self.questions[13]
        }

    def select_questions(self, selected_enums: List[SurveyQuestionEnum]):
        '''
        Select 1-3 questions from the dropdown list of questions.
        
        :param selected_enums: List of enum values of the selected questions.
        :raises ValueError: If number of questions is not between 1 and 3, or if duplicate questions are selected.
        '''
        if not selected_enums:
            raise ValueError("At least 1 question must be selected.")
        if len(selected_enums) > 3:
            raise ValueError("Maximum of 3 questions can be selected.")
        if len(selected_enums) != len(set(selected_enums)):
            raise ValueError("Duplicate questions are not allowed.")
        
        self.selected_questions = [self.question_map[enum] for enum in selected_enums]

    def get_selected_questions(self) -> list:
        '''
        Get the list of selected questions.
        
        :return: List of selected questions.
        '''
        return self.selected_questions
    


class FocusGroupAnalysis(OpenaiClient):
    '''
    Analyze ad from the image ad data
    - target_audiences: Dict[str, Any]
    - ad_visual_elements: Dict[str, Any]
    - ad_engagement_elements: Dict[str, Any]
    - ad_text_tone: Dict[str, Any]
    '''
    def __init__(self , target_audiences:Dict[str, Any] , image_ad_data:Dict[str, Any] , api_key: str):
        super().__init__(api_key=os.getenv("OPENAI_API_KEY"))
        self.target_audiences = target_audiences
        self.image_ad_data = image_ad_data
        self.survey = SurveyQuestions()
        self.focus_group_responses = []

    async def set_survey_questions(self, selected_questions: List[SurveyQuestionEnum]):
        """Set the survey questions using the enum values"""
        self.survey.select_questions(selected_questions)

    async def add_focus_group_response(self, persona_id: str, responses: Dict[str, str]):
        """Add a focus group response for analysis"""
        self.focus_group_responses.append({
            "persona_id": persona_id,
            "responses": responses
        })

    async def analyze_focus_group_responses(self) -> Dict[str, Any]:
        """Analyze all focus group responses"""
        try:
            prompt_content = await read_prompt_file(PromptFile.ANALYZE_FOCUS_GROUP.value)
            
            analysis_data = {
                "questions": self.survey.get_selected_questions(),
                "responses": self.focus_group_responses,
                "image_ad_data": self.image_ad_data,
                "target_audiences": self.target_audiences
            }
            
            prompt_content = await add_variable_to_prompt(
                prompt_content, 
                "analysis_data", 
                analysis_data
            )

            response = await self.aclient.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {
                        "role": "system",
                        "content": """You are an AI assistant specializing in analyzing focus group responses 
                        for advertising effectiveness. Analyze the responses considering the target audience 
                        profiles and ad elements to provide meaningful insights."""
                    },
                    {
                        "role": "user",
                        "content": prompt_content
                    }
                ],
                temperature=0.2,
                max_tokens=3000,
                response_format={"type": "json_object"}
            )

            return response.choices[0].message.content

        except Exception as e:
            self.log_error(f"Error analyzing focus group responses: {str(e)}")
            raise

    async def generate_and_analyze_responses(self, personas: List[str]) -> Dict[str, Any]:
        """Generate responses for each persona and analyze them."""
        persona_impersonator = PersonaImpersonation(api_key=os.getenv("OPENAI_API_KEY"))
        questions = self.survey.get_selected_questions()

        for persona in personas:
            responses = await persona_impersonator.generate_persona_response(persona, questions)
            await self.add_focus_group_response(persona, responses)

        return await self.analyze_focus_group_responses()


class PersonaImpersonation(OpenaiClient):
    def __init__(self, api_key: str):
        super().__init__(api_key=os.getenv("OPENAI_API_KEY"))

    async def generate_persona_response(self, persona: str, questions: List[str]) -> Dict[str, str]:
        """Generate responses for a given persona and list of questions."""
        try:
            # Read the prompt content from the persona_response.txt file
            prompt_content = await read_prompt_file(PromptFile.PERSONA_RESPONSE.value)
            
            # Add the persona and questions to the prompt
            prompt_content = await add_variable_to_prompt(prompt_content, "persona", persona)
            prompt_content = await add_variable_to_prompt(prompt_content, "questions", "\n".join(questions))

            response = await self.aclient.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {
                        "role": "system",
                        "content": """You are an AI assistant tasked with impersonating a persona to provide 
                        realistic and coherent responses to survey questions."""
                    },
                    {
                        "role": "user",
                        "content": prompt_content
                    }
                ],
                temperature=0.7,
                max_tokens=1000,
                response_format={"type": "json_object"}
            )
            # Assuming the response is structured as a JSON object with question-response pairs
            return response.choices[0].message.content

        except Exception as e:
            self.log_error(f"Error generating persona response: {str(e)}")
            raise

