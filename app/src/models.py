import json


class TargetAudienceForm:
    def __init__(self,description: str, age_range: str, gender: str, location: str, interests: list[str], pain_points: list[str]):
        self.description = description
        self.age_range = age_range
        self.gender = gender
        self.location = location
        self.interests = interests
        self.pain_points = pain_points
    
    def to_json(self) -> str:
        return json.dumps({
            "description": self.description,
            "age_range": self.age_range,
            "gender": self.gender,
            "location": self.location,
            "interests": self.interests,
            "pain_points": self.pain_points
        })