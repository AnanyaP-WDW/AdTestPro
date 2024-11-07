from src import (
    CreateSyntheticAgents,
    TargetAudienceForm,
    ExtractImageAdData,
    PromptFile,
    PersonaImpersonation,
    SurveyQuestions,
    SurveyQuestionEnum
)
import os
import asyncio
import ast

async def main():
    target_audience_form = TargetAudienceForm(
        description="A health-conscious individual passionate about plant-based living and environmental sustainability",
        age_range="25-45",
        gender="Any",
        location="United States",
        interests=["Veganism", "Plant-based cooking", "Sustainability", "Animal rights", "Ethical consumption"],
        pain_points=["Finding quality vegan alternatives", "Dining out with limited options", "Maintaining balanced nutrition", "High cost of specialty vegan products", "Social situations around food choices"]
    )

    create_synthetic_agents = CreateSyntheticAgents(target_audience_form, api_key=os.getenv("OPENAI_API_KEY"))
    target_audience_agents = await create_synthetic_agents.generate_response()

    try:
        target_audience_agents_data = ast.literal_eval(target_audience_agents)

        print(f"target_audience_agents_data: {target_audience_agents_data}/n/n")
        
        print(f"type(target_audience_agents_data): {type(target_audience_agents_data)}/n/n")
        
        if not isinstance(target_audience_agents_data, dict):
            raise ValueError("Parsed data is not a valid JSON object")
        
        if 'personas' not in target_audience_agents_data:
            raise ValueError("Missing 'personas' key in the response")
        
        personas = target_audience_agents_data.get('personas')
        
        if len(personas) < 3:
            raise ValueError("Less than 3 personas generated")
    except (ValueError, SyntaxError) as e:
        raise ValueError(f"Error retrieving personas: {e}")

    print(f"personas: {personas} /n/n")
    print(f"target_audience_agents: {target_audience_agents}/n/n")

    print("Extract Image Ad Data")

    image_analyzer = ExtractImageAdData(image_path="test.jpg", api_key=os.getenv("OPENAI_API_KEY"))

    tasks = [
        asyncio.create_task(image_analyzer.call_openai_api(prompt_file=PromptFile.EXTRACT_VISUAL_ELEMENTS)),
        asyncio.create_task(image_analyzer.call_openai_api(prompt_file=PromptFile.EXTRACT_TEXT_TONE)),
        asyncio.create_task(image_analyzer.call_openai_api(prompt_file=PromptFile.EXTRACT_ENGAGEMENT_ELEMENTS))
    ]

    # Run tasks concurrently
    analysis_results = await asyncio.gather(*tasks)
    print(f"analysis_results: {analysis_results}/n/n")

    # Create SurveyQuestions instance and select questions
    survey_questions = SurveyQuestions()
    survey_questions.select_questions([
        SurveyQuestionEnum.ACTION,
        SurveyQuestionEnum.BRAND_RECALL_SCORE,
        SurveyQuestionEnum.APPEAL_SCORE
    ])
    #can only select max 3 questions
    selected_questions = survey_questions.get_selected_questions()

    persona_impersonation = PersonaImpersonation(api_key=os.getenv("OPENAI_API_KEY"), questions=selected_questions)

    [await persona_impersonation.generate_persona_response(persona=persona, persona_id=persona_id) 
                        for persona_id, persona in enumerate(personas, start=1)]

    all_responses = persona_impersonation.persona_responses.get_all_responses()

    print(f"all_responses: {all_responses}/n/n")

asyncio.run(main())
