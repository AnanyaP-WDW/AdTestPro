from fastapi import FastAPI, HTTPException, UploadFile, File, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import os
import uvicorn
import ast
import python_multipart
import asyncio
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi import Request
from sqlalchemy.orm import Session

from app.src.engine import CreateSyntheticAgents, TargetAudienceForm
from app.src.extract import ExtractImageAdData, PromptFile
from app.src.analyze import SurveyQuestions, SurveyQuestionEnum, PersonaImpersonation
from app.dependencies import get_db
from app.models.database import AdImage, AdAnalysis, TargetAudience, ImpersonationResult
import json


app = FastAPI(
    title="AdTestPro",
    description="Synthetic Focus Group testing for ad creatives",
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

templates = Jinja2Templates(directory="app/templates")
app.mount("/static", StaticFiles(directory="app/static"), name="static")

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

class PersonaImpersonationRequest(BaseModel):
    personas: List[Dict[str, Any]]
    selected_questions: List[str]

# Health check endpoint
@app.get("/health")
async def health_check():
    return {"status": "healthy"}

# Generate agents endpoint
@app.post("/api/generate-agents")
async def generate_agents(
    target_audience: TargetAudienceRequest,
    db: Session = Depends(get_db)
):
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
        
        # Save to database
        db_target_audience = TargetAudience(
            description=target_audience.description,
            age_range=target_audience.age_range,
            gender=target_audience.gender,
            location=target_audience.location,
            interests=target_audience.interests,
            pain_points=target_audience.pain_points,
            generated_personas=agents_dict
        )
        db.add(db_target_audience)
        db.commit()
        db.refresh(db_target_audience)

        return {
            "status": "success",
            "data": agents_dict
        }
    
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )

@app.post("/api/analyze-ad-image", response_model=ImageAnalysisResponse)
async def analyze_ad_image(
    file: UploadFile = File(...),
    prompt_types: List[str] = ["engagement_elements", "text_tone", "visual_elements"],
    db: Session = Depends(get_db)
):
    try:
        temp_path = f"temp_{file.filename}"
        try:
            # Read file contents
            contents = await file.read()
            
            # Save to database
            db_image = AdImage(
                filename=file.filename,
                image_data=contents
            )
            db.add(db_image)
            db.commit()
            db.refresh(db_image)

            # Write to temporary file for analysis
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

            tasks = [ asyncio.create_task(image_analyzer.call_openai_api(prompt_file=PromptFile.EXTRACT_VISUAL_ELEMENTS)),
                      asyncio.create_task(image_analyzer.call_openai_api(prompt_file=PromptFile.EXTRACT_TEXT_TONE)),
                      asyncio.create_task(image_analyzer.call_openai_api(prompt_file=PromptFile.EXTRACT_ENGAGEMENT_ELEMENTS))
                     ]  

            # Run tasks concurrently
            analysis_results = await asyncio.gather(*tasks)
            
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

            # Save analysis results
            db_analysis = AdAnalysis(
                ad_image_id=db_image.id,
                engagement_elements=processed_results.get("engagement_elements"),
                text_tone=processed_results.get("text_tone"),
                visual_elements=processed_results.get("visual_elements")
            )
            db.add(db_analysis)
            db.commit()

            return {
                "status": "success",
                "data": processed_results
            }

        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error analyzing image: {str(e)}"
        )

@app.post("/api/run-impersonation")
async def run_impersonation(
    request: PersonaImpersonationRequest,
    db: Session = Depends(get_db)
):
    try:
        # Create SurveyQuestions instance
        survey_questions = SurveyQuestions()
        
        # Convert string question names to enums
        question_enum_map = {
            "action": SurveyQuestionEnum.ACTION,
            "brand_recall": SurveyQuestionEnum.BRAND_RECALL_SCORE,
            "appeal": SurveyQuestionEnum.APPEAL_SCORE,
            "emotions": SurveyQuestionEnum.EMOTIONS,
            "target_demographic": SurveyQuestionEnum.TARGET_DEMOGRAPHIC,
            "call_to_action": SurveyQuestionEnum.CALL_TO_ACTION,
            "tone_and_style": SurveyQuestionEnum.TONE_AND_STYLE,
            "positives": SurveyQuestionEnum.POSITIVES,
            "negatives": SurveyQuestionEnum.NEGATIVES,
            "improvements": SurveyQuestionEnum.IMPROVEMENTS,
            "engagement": SurveyQuestionEnum.ENGAGEMENT_SCORE,
            "believability": SurveyQuestionEnum.BELIEVABILITY_SCORE,
            "relevance": SurveyQuestionEnum.RELEVANCE_SCORE,
            "trustworthy": SurveyQuestionEnum.TRUSTWORTHY_SCORE
        }
        
        # Convert selected questions to enums
        selected_enums = [question_enum_map[q] for q in request.selected_questions]
        
        # Select questions
        survey_questions.select_questions(selected_enums)
        selected_questions = survey_questions.get_selected_questions()

        # Initialize PersonaImpersonation
        persona_impersonation = PersonaImpersonation(
            api_key=os.getenv("OPENAI_API_KEY"), 
            questions=selected_questions
        )

        # Generate responses for each persona
        for persona_id, persona in enumerate(request.personas, start=1):
            await persona_impersonation.generate_persona_response(
                persona=persona, 
                persona_id=persona_id
            )

        # Get all responses
        all_responses = persona_impersonation.persona_responses.get_all_responses()

        # Save results to database
        db_impersonation = ImpersonationResult(
            ad_image_id=None,  # Autoincrement will handle this
            target_audience_id=None,  # Autoincrement will handle this
            selected_questions=request.selected_questions,
            responses=all_responses
        )
        db.add(db_impersonation)
        db.commit()
        db.refresh(db_impersonation)

        return {
            "status": "success",
            "data": all_responses
        }

    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error running persona impersonation: {str(e)}"
        )

@app.get("/")
async def root(request: Request):
    """Serve the base template"""
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/home")
async def home(request: Request):
    """Serve the home template"""
    return templates.TemplateResponse("home.html", {"request": request})

@app.get("/generate-participants")
async def agents_page(request: Request):
    return templates.TemplateResponse("agents.html", {"request": request})

@app.get("/dashboard")
async def agents_page(request: Request):
    return templates.TemplateResponse("agents.html", {"request": request})

@app.get("/run-focusgroup-survey")
async def analyze_page(request: Request):
    return templates.TemplateResponse("run-focusgroup-survey.html", {"request": request})

@app.get("/agents-content")
async def agents_content(request: Request):
    return templates.TemplateResponse(
        "agents.html", 
        {"request": request}, 
        headers={"HX-Push-Url": "/agents"}
    )

@app.get("/analyze-content")
async def analyze_content(request: Request):
    return templates.TemplateResponse(
        "analyze.html", 
        {"request": request}, 
        headers={"HX-Push-Url": "/analyze"}
    )

# Add this new endpoint to get the questions dynamically
@app.get("/api/survey-questions")
async def get_survey_questions(request: Request):
    # Create SurveyQuestions instance to get all available questions
    survey_questions = SurveyQuestions()
    
    # Get all available questions as a dict with enum value -> question text
    questions = {
        "action": "What action are you encouraged to take?",
        "brand_recall": "How is the Brand recall of this ad creative?",
        "appeal": "How appealing does this ad creative feel?",
        "emotions": "What emotions does this ad evoke?",
        "target_demographic": "Who is the target demographic?",
        "call_to_action": "How effective is the call to action?",
        "tone_and_style": "What is the tone and style of the ad?",
        "positives": "What are the positive aspects?",
        "negatives": "What are the negative aspects?",
        "improvements": "What improvements would you suggest?",
        "engagement": "How engaging is this ad?",
        "believability": "How believable is this ad?",
        "relevance": "How relevant is this ad to you?",
        "trustworthy": "How trustworthy does this ad feel?"
    }
    
    # Return the template response instead of JSON
    return templates.TemplateResponse(
        "partials/survey_questions.html", 
        {"request": request, 
         "questions": survey_questions.question_map }
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
