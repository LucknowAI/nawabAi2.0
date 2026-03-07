import requests
import json
import aiohttp
import asyncio
import tenacity
from src.config.settings import Settings

class APIHandler:
    BASE_URL = "https://google.serper.dev"

    def __init__(self):
        pass  # Key is read fresh on every call to avoid stale init-time values

    def _get_headers(self) -> dict:
        api_key = Settings.SERPER_API_KEY
        if not api_key:
            raise ValueError("SERPER_API_KEY is not set in environment variables.")
        return {
            'X-API-KEY': api_key,
            'Content-Type': 'application/json'
        }

    @tenacity.retry(
        wait=tenacity.wait_random_exponential(multiplier=1, min=1, max=60), # Adjust min/max as needed
        stop=tenacity.stop_after_attempt(5),  # Adjust attempts as needed
        retry=tenacity.retry_if_exception_type((aiohttp.ClientError, asyncio.TimeoutError)),
        reraise=True
    )
    async def call_api(self, endpoint, payload):
        url = f"{self.BASE_URL}/{endpoint}"
        try:
            headers = self._get_headers()
            # Configure timeout for the session
            timeout = aiohttp.ClientTimeout(total=Settings.API_TIMEOUT)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, headers=headers, json=payload) as response:
                    response.raise_for_status()  # Raises an exception for 4XX/5XX status codes
                    return {"status": 1, "data": await response.json()}
        except aiohttp.ClientResponseError as e: # Specific exception for HTTP errors
            # You could log e.status and e.message here
            return {"status": 0, "error": f"API request failed with status {e.status}: {e.message}", "details": str(e)}
        except asyncio.TimeoutError as e:
            return {"status": 0, "error": f"API request timed out after {Settings.API_TIMEOUT} seconds.", "details": str(e)}
        except aiohttp.ClientError as e: # Catch other client errors (e.g., connection issues)
            return {"status": 0, "error": "API request failed due to a client error.", "details": str(e)}
        except Exception as e: # Catch-all for any other unexpected errors during the API call
            # It's good to log this e comprehensively
            return {"status": 0, "error": "An unexpected error occurred during the API call.", "details": str(e)}

    async def maps_api(self, keywords, coordinates: str = "@26.8488213,80.8601114,12z"):
        payload = {
            "q": " ".join(keywords),
            "ll": coordinates,
        }
        return await self.call_api("maps", payload)

    async def news_api(self, keywords, location: str = "Lucknow, Uttar Pradesh, India"):
        payload = {
            "q": " ".join(keywords),
            "location": location,
            "gl": "in",
            "tbs": "qdr:w",
        }
        return await self.call_api("news", payload)

    async def video_api(self, keywords, location: str = "Lucknow, Uttar Pradesh, India"):
        payload = {
            "q": " ".join(keywords),
            "location": location,
            "gl": "in",
        }
        return await self.call_api("videos", payload)

    async def search_api(self, query: str):
        """Perform a Google web search via Serper and return organic results."""
        payload = {"q": query}
        return await self.call_api("search", payload)

    async def process_input(self, input_data):
        if not isinstance(input_data, dict):
            return {"status": 0, "error": "Invalid input format. Expected a dictionary."}

        response = input_data.get("response", {})
        if not response:
            return {"status": 0, "error": "No 'response' key found in input data."}

        api_needed = input_data.get("api_needed", len(response))
        tasks = []
        results = {}

        for api_name, keywords in response.items():
            if not isinstance(keywords, list) or not keywords:
                results[api_name] = {"status": 0, "error": "Keywords should be a non-empty list."}
                continue

            if api_name == "google_maps_api":
                tasks.append((api_name, self.maps_api(keywords)))
            elif api_name == "google_news_api":
                tasks.append((api_name, self.news_api(keywords)))
            elif api_name == "google_video_api":
                tasks.append((api_name, self.video_api(keywords)))
            else:
                results[api_name] = {"status": 0, "error": f"Unknown API: {api_name}"}

        # Execute all API calls in parallel
        if tasks:
            api_results = await asyncio.gather(*[task[1] for task in tasks])
            for (api_name, _), result in zip(tasks, api_results):
                results[api_name] = result

        return results if len(results) > 1 else next(iter(results.values()))

# Usage example
if __name__ == "__main__":
    handler = APIHandler()
    input_data = {
        "response": {
            # "google_maps_api": ["hospitals in Lucknow"],
            "google_news_api": ["latest news about Lucknow"],
            # "google_video_api": ["about lucknow"]
         },
        "api_needed": 3
    }
    loop = asyncio.get_event_loop()
    output = loop.run_until_complete(handler.process_input(input_data))
    print(json.dumps(output, indent=2))