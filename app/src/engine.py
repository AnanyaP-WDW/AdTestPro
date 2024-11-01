
import os
from .models import TargetAudienceForm
from .audience import CreateSyntheticAgents
from .extract import ExtractImageAdData
from .utils import PromptFile
from .analyze import FocusGroupAnalysis


# run the engine
# extract all the information form ad creative
# create target audience
# use the target audience and ad creative information to create synthetic agents to run the focus group
# run the focus group
# analyze the focus group responses
# return the analysis

async def run_engine():
    target_audience_form = TargetAudienceForm(
            description="A health-conscious individual interested in plant-based diets",
            age_range="25-45",
            gender="Female",
            location="USA",
            interests=["Veganism", "Healthy Eating", "Sustainability", "Animal Welfare", "Organic Foods"],
            pain_points=["Finding high-quality vegan products", "Ensuring balanced nutrition", "Affordability of vegan options", "Access to convenient plant-based meals"]
        )

    create_synthetic_agents = CreateSyntheticAgents(target_audience_form, api_key=os.getenv("OPENAI_API_KEY"))
    target_audience_agents = await create_synthetic_agents.generate_response()
    
    print("Generated Target Audience Personas:")
    print(target_audience_agents)

    extract_image_ad_data = ExtractImageAdData(image_path="test.jpg", api_key=os.getenv("OPENAI_API_KEY"))
    ad_data = await extract_image_ad_data.generate_response()
    
    print("\nExtracted Image Ad Data:")
    print(engagement_elements)
    