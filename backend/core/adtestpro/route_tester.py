class RouteTester:
    def __init__(self):
        self.name = "RouteTester"

    def test_route(self):
        return {
            "status": "success",
            "message": "Route test successful",
            "tester": self.name
        } 