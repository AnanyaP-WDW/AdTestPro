from src import CreateSyntheticAgents, TargetAudienceForm, ExtractImageAdData, PromptFile
import os
import asyncio




async def main():

    target_audience_form = TargetAudienceForm(
    description="A tech-savvy professional with a passion for fitness and wellness",
    age_range="30-50",
    gender="Male",
    location="Canada",
    interests=["Technology", "Fitness", "Wellness", "Gadgets", "Healthy Living"],
    pain_points=["Balancing work and fitness", "Finding reliable fitness gadgets", "Staying updated with wellness trends", "Access to personalized fitness plans"]
)

    create_synthetic_agents = CreateSyntheticAgents(target_audience_form, api_key=os.getenv("OPENAI_API_KEY"))

    target_audience_agents = await create_synthetic_agents.generate_response()

    print(target_audience_agents)

    # print("xxxxx...................................xxxxx")

    # print("Extract Image Ad Data")

    # extract_image_ad_data = ExtractImageAdData(image_path="test.jpg", api_key=os.getenv("OPENAI_API_KEY"))

    # print(extract_image_ad_data)

    # image_ad_data = await extract_image_ad_data.call_openai_api(prompt_file=PromptFile.EXTRACT_ENGAGEMENT_ELEMENTS)

    # print(image_ad_data)

    #analyse resutls




asyncio.run(main())
