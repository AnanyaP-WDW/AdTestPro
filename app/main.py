from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import os
import uvicorn
import ast
import python_multipart
import asyncio

from app.src.engine import CreateSyntheticAgents, TargetAudienceForm
from app.src.extract import ExtractImageAdData, PromptFile


app = FastAPI(
    title="Synthetic Agents API",
    description="API for generating synthetic audience agents",
    version="1.0.0"
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, replace with specific origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class TargetAudienceRequest(BaseModel):
    description: str
    age_range: str
    gender: str
    location: str
    interests: List[str]
    pain_points: List[str]

class ImageAnalysisResponse(BaseModel):
    status: str
    data: Dict[str, Any]

@app.post("/api/generate-agents")
async def generate_agents(target_audience: TargetAudienceRequest):
    try:
        # Convert the request model to TargetAudienceForm
        target_audience_form = TargetAudienceForm(
            description=target_audience.description,
            age_range=target_audience.age_range,
            gender=target_audience.gender,
            location=target_audience.location,
            interests=target_audience.interests,
            pain_points=target_audience.pain_points
        )

        # Initialize the synthetic agents creator
        creator = CreateSyntheticAgents(
            target_audience_form, 
            api_key=os.getenv("OPENAI_API_KEY")
        )

        # Generate the response
        
        agents = await creator.generate_response()
        
        try:
            agents_dict = ast.literal_eval(agents)
        except (ValueError, SyntaxError) as e:
            raise HTTPException(
                status_code=500,
                detail=f"Error parsing agents response: {str(e)}"
            )
        
        return {
            "status": "success",
            "data": agents_dict
        }
    
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

@app.post("/api/analyze-ad-image", response_model=ImageAnalysisResponse)
async def analyze_ad_image(
    file: UploadFile = File(...),
    prompt_types: List[str] = ["engagement_elements", "text_tone", "visual_elements"]
):
    try:
        temp_path = f"temp_{file.filename}"
        try:
            contents = await file.read()
            with open(temp_path, "wb") as f:
                f.write(contents)

            image_analyzer = ExtractImageAdData(
                image_path=temp_path,
                api_key=os.getenv("OPENAI_API_KEY")
            )

            prompt_mapping = {
                "engagement_elements": PromptFile.EXTRACT_ENGAGEMENT_ELEMENTS,
                "text_tone": PromptFile.EXTRACT_TEXT_TONE,
                "visual_elements": PromptFile.EXTRACT_VISUAL_ELEMENTS
            }

            prompt_types = prompt_types[0].split(",")

            print("before task")
            tasks = [ asyncio.create_task(image_analyzer.call_openai_api(prompt_file=PromptFile.EXTRACT_VISUAL_ELEMENTS)),
                      asyncio.create_task(image_analyzer.call_openai_api(prompt_file=PromptFile.EXTRACT_TEXT_TONE)),
                      asyncio.create_task(image_analyzer.call_openai_api(prompt_file=PromptFile.EXTRACT_ENGAGEMENT_ELEMENTS))
                     ]  

            # Run tasks concurrently
            analysis_results = await asyncio.gather(*tasks)
            # tasks = [await image_analyzer.call_openai_api(prompt_file=prompt_mapping[pt]) for pt in prompt_types]
            # analysis_results = await asyncio.gather(*tasks)
            print("after task")
            # Process results
            processed_results = {}
            print(f"prompt types: {prompt_types}, and type : {type(prompt_types)}")
            for pt, result in zip(prompt_types, analysis_results):
                try:
                    # If result is a string, parse it
                    if isinstance(result, str):
                        parsed_result = ast.literal_eval(result)
                        # If parsed result is a list with one item, take the first item
                        if isinstance(parsed_result, list) and len(parsed_result) == 1:
                            processed_results[pt] = parsed_result[0]
                        else:
                            processed_results[pt] = parsed_result
                    else:
                        processed_results[pt] = result
                except (ValueError, SyntaxError) as e:
                    raise HTTPException(
                        status_code=500,
                        detail=f"Error parsing analysis result for {pt}: {str(e)}"
                    )

            return {
                "status": "success",
                "data": processed_results
            }

        finally:
            # Clean up temporary file
            if os.path.exists(temp_path):
                os.remove(temp_path)

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error analyzing image: {str(e)}"
        )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
