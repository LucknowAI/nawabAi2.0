import requests
import json
import aiohttp
from src.config.settings import Settings
class APIHandler:
    BASE_URL = "https://google.serper.dev"
    API_KEY = Settings.SERPER_API_KEY

    def __init__(self):
        self.headers = {
            'X-API-KEY': self.API_KEY,
            'Content-Type': 'application/json'
        }

    async def call_api(self, endpoint, payload):
        url = f"{self.BASE_URL}/{endpoint}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=self.headers, json=payload) as response:
                    response.raise_for_status()
                    return {"status": 1, "data": await response.json()}
        except aiohttp.ClientError as e:
            return {"status": 0, "error": str(e)}

    async def maps_api(self, keywords):
        payload = {
            "q": " ".join(keywords),
            "ll": "@26.8488213,80.8601114,12z"  # Default to Lucknow coordinates
        }
        return await self.call_api("maps", payload)

    async def news_api(self, keywords):
        payload = {
            "q": " ".join(keywords),
            "location": "Lucknow, Uttar Pradesh, India",
            "gl": "in",
            "tbs": "qdr:w"
        }
        return await self.call_api("news", payload)

    async def video_api(self, keywords):
        payload = {
            "q": " ".join(keywords),
            "location": "Lucknow, Uttar Pradesh, India",
            "gl": "in"
        }
        return await self.call_api("videos", payload)

    async def process_input(self, input_data):
        if not isinstance(input_data, dict):
            return {"status": 0, "error": "Invalid input format. Expected a dictionary."}

        response = input_data.get("response", {})
        if not response:
            return {"status": 0, "error": "No 'response' key found in input data."}

        api_needed = input_data.get("api_needed", len(response))
        results = {}

        for api_name, keywords in response.items():
            
            if not isinstance(keywords, list) or not keywords:
                results[api_name] = {"status": 0, "error": "Keywords should be a non-empty list."}
                continue

            if api_name == "google_maps_api":
                results[api_name] = await self.maps_api(keywords)
            elif api_name == "google_news_api":
                results[api_name] = await self.news_api(keywords)
            elif api_name == "google_video_api":
                results[api_name] = await self.video_api(keywords)
            else:
                results[api_name] = {"status": 0, "error": f"Unknown API: {api_name}"}

        return results if len(results) > 1 else next(iter(results.values()))

# Usage example
# if __name__ == "__main__":
#     # Test cases
#     test_cases = [
#         {
#             "response": {
#                 "google_news_api": ["latest", "technology"]
#             }
#         },
#         {
#             "api_needed": 1,
#             "response": {
#                 "google_news_api": ["latest", "news", "Lucknow"],
#                 "google_video_api": ["about lucknow"]
#             }
#         },
#         {
#             "response": {
#                 "google_maps_api": ["hospitals", "Lucknow"]
#             }
#         },
#         {
#             "api_needed": 2,
#             "response": {
#                 "google_news_api": ["technology", "startups"],
#                 "google_video_api": ["tech news"],
#                 "google_maps_api": ["tech parks"]
#             }
#         },
#         # Edge cases
#         {},
#         {"response": {}},
#         {"response": {"unknown_api": ["test"]}},
#         {"response": {"google_maps_api": []}},
#     ]

#     for i, test_case in enumerate(test_cases, 1):
#         print(f"\nTest case {i}:")
#         print("Input:", test_case)
#         result = api_handler.process_input(test_case)
#         print("Output:", result)