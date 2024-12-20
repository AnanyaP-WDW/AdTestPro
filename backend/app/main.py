from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from adtestpro import route_tester

app = FastAPI(title="API Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {"message": "Hello World"}

@app.get("/test")
async def test():
    # Using our custom adtestpro library
    route_test = route_tester.RouteTester()
    return route_test.test_route() 