import json
import uuid
import os
from datetime import datetime
from src.languageModel.llms.lite_llm import LiteLLMClient
from src.config.settings import Settings
from src.tools.serper import APIHandler
from src.languageModel.prompts.translation.translationPromptv1 import TRANSLATION_USER_PROMPT
from src.languageModel.prompts.response.responsePromptv1 import RESPONSE_USER_PROMPT
import re
import hashlib
from typing import Optional, Dict, Any

class QueryProcessor:
    def __init__(self, queue_client=None, cache_client=None, log_folder="query_logs"):
        self.max_tokens = 16000  # Max tokens for API call
        self.input_token_limit = 16384
        self.temperature = 0.5
        self.top_p = 0.9
        self.lite_llm_handler = LiteLLMClient(api_key=Settings.GEMINI_API_KEY, model_name="gemini/gemini-2.0-flash-lite")
        self.api_handler = APIHandler()
        self.queue_client = queue_client
        self.cache_client = cache_client
        self.log_folder = log_folder
        if not os.path.exists(self.log_folder):
            os.makedirs(self.log_folder)

    def extract_json_string(self, json_string):
    # Handle empty responses
        if not json_string or json_string.isspace():
            print(f"Warning: Empty response received from LLM")
            return {"api_needed": 0, "response": "I'm sorry, I couldn't process your request. Please try again."}
        
        # Try to find JSON content within markdown code blocks
        json_match = re.search(r'```(?:json)?\s*\n([\s\S]*?)\n```', json_string)
        if json_match:
            json_string = json_match.group(1).strip()
        else:
            # Remove the code block markers if they exist
            json_string = json_string.strip("```json\n").strip("```").strip()
        
        # Parse the JSON string
        try:
            parsed_json = json.loads(json_string)
            return parsed_json
        except json.JSONDecodeError as e:
            print(f"Error decoding JSON: {e}, Raw response: {json_string[:500]}")
            # Provide a fallback response
            return {
                "api_needed": 0,
                "response": "I encountered an issue processing your request. Here's what I received: " + json_string
            }
    
    def _extract_links_from_api_results(self, api_results):
        """
        Extract links from API results to make them more accessible to the LLM
        """
        extracted_links = {}
        
        if isinstance(api_results, dict):
            # Handle the case where we get a single API result
            if "data" in api_results and isinstance(api_results["data"], dict):
                data = api_results["data"]
                
                # Extract links from maps API
                if "places" in data:
                    places_links = []
                    for place in data.get("places", []):
                        if "link" in place:
                            places_links.append({
                                "title": place.get("title", ""),
                                "link": place.get("link", ""),
                                "type": "map"
                            })
                    if places_links:
                        extracted_links["places"] = places_links
                
                # Extract links from video API
                if "organic" in data and "video" in api_results.get("api_name", ""):
                    video_links = []
                    for video in data.get("organic", []):
                        if "link" in video:
                            video_links.append({
                                "title": video.get("title", ""),
                                "link": video.get("link", ""),
                                "type": "video"
                            })
                    if video_links:
                        extracted_links["videos"] = video_links
                
                # Extract links from news API
                if "news" in data:
                    news_links = []
                    for news in data.get("news", []):
                        if "link" in news:
                            news_links.append({
                                "title": news.get("title", ""),
                                "link": news.get("link", ""),
                                "type": "news"
                            })
                    if news_links:
                        extracted_links["news"] = news_links
            
            # Handle the case of multiple API results 
            else:
                for api_name, api_result in api_results.items():
                    if isinstance(api_result, dict) and "data" in api_result and api_result.get("status", 0) == 1:
                        data = api_result["data"]
                        
                        if "google_maps" in api_name.lower() and "places" in data:
                            places_links = []
                            for place in data.get("places", []):
                                if "link" in place:
                                    places_links.append({
                                        "title": place.get("title", ""),
                                        "link": place.get("link", ""),
                                        "type": "map"
                                    })
                            if places_links:
                                extracted_links["places"] = places_links
                        
                        if "google_video" in api_name.lower() and "organic" in data:
                            video_links = []
                            for video in data.get("organic", []):
                                if "link" in video:
                                    video_links.append({
                                        "title": video.get("title", ""),
                                        "link": video.get("link", ""),
                                        "type": "video"
                                    })
                            if video_links:
                                extracted_links["videos"] = video_links
                        
                        if "google_news" in api_name.lower() and "news" in data:
                            news_links = []
                            for news in data.get("news", []):
                                if "link" in news:
                                    news_links.append({
                                        "title": news.get("title", ""),
                                        "link": news.get("link", ""),
                                        "type": "news"
                                    })
                            if news_links:
                                extracted_links["news"] = news_links
        
        return extracted_links
    
    def _normalize_query(self, query: str) -> str:
        """Normalize query for more effective caching"""
        # Remove extra whitespace and convert to lowercase
        normalized = " ".join(query.lower().split())
        # Remove punctuation that doesn't affect meaning
        normalized = re.sub(r'[,.!?]', '', normalized)
        return normalized

    def _generate_cache_key(self, query: str) -> str:
        """Generate an efficient cache key"""
        normalized_query = self._normalize_query(query)
        # Use first 32 chars of normalized query + md5 hash
        prefix = normalized_query[:32].strip()
        hash_suffix = hashlib.md5(normalized_query.encode()).hexdigest()[:8]
        return f"q:{prefix}:{hash_suffix}"

    async def _get_from_cache(self, query: str) -> Optional[Dict[str, Any]]:
        """Get result from cache with error handling"""
        if not self.cache_client:
            return None
            
        try:
            cache_key = self._generate_cache_key(query)
            cached_result = await self.cache_client.get(cache_key)
            if cached_result:
                return json.loads(cached_result, strict=False)
                
            # Try normalized cache
            normalized_key = f"norm:{self._normalize_query(query)}"
            normalized_result = await self.cache_client.get(normalized_key)
            if normalized_result:
                return json.loads(normalized_result, strict=False)
        except (json.JSONDecodeError, Exception) as e:
            print(f"Cache error for query '{query[:50]}...': {str(e)}")
        return None

    async def _set_in_cache(self, query: str, result: Dict[str, Any], expire: int = 3600) -> None:
        """Set result in cache with error handling"""
        if not self.cache_client:
            return
            
        try:
            cache_key = self._generate_cache_key(query)
            cache_data = json.dumps(result, ensure_ascii=False)
            await self.cache_client.set(cache_key, cache_data, expire=expire)
            
            # Cache prefetching: Store normalized version for similar queries
            normalized_key = f"norm:{self._normalize_query(query)}"
            await self.cache_client.set(normalized_key, cache_data, expire=expire)
        except Exception as e:
            print(f"Cache set error for query '{query[:50]}...': {str(e)}")

    async def process_query(self, query: str) -> Dict[str, Any]:
        try:
            # Try cache first
            cached_result = await self._get_from_cache(query)
            if cached_result:
                return cached_result

            log_data = {
                "uuid": str(uuid.uuid4()),
                "timestamp": datetime.now().isoformat(),
                "query": query,
                "stages": []
            }

            # First stage: Translation and API determination
            combined_prompt = TRANSLATION_USER_PROMPT + "\n" + query + "\n Output in JSON format:"
            result = await self.lite_llm_handler.generate_response(combined_prompt)
            if not result:
                raise ValueError("Empty response from LLM")
                
            log_data["stages"].append({"stage": "translation", "result": result})
            
            result = self.extract_json_string(result)
            if not isinstance(result, dict):
                raise ValueError("Invalid JSON response from LLM")
                
            if result.get("api_needed") == 1:
                # Second stage: Process with API in parallel
                result_api = await self.api_handler.process_input(result)
                if not result_api:
                    raise ValueError("Empty response from API handler")
                
                # Extract links into a more structured format
                extracted_links = self._extract_links_from_api_results(result_api)
                
                final_api_output = {
                    "User Query": query, 
                    "api_results": result_api,
                    "extracted_links": extracted_links
                }
                log_data["stages"].append({"stage": "api_processing", "result": result_api})

                # Third stage: Generate final response with optimized settings
                api_output_json = json.dumps(final_api_output, indent=2, ensure_ascii=False)
                combined_final_prompt = RESPONSE_USER_PROMPT + "\n" + api_output_json + "\n Output in Markdown format:"
                
                final_result = await self.lite_llm_handler.generate_response(
                    combined_final_prompt,
                    temperature=0.7,
                    top_p=0.95,
                    max_tokens=1000
                )
                if not final_result:
                    raise ValueError("Empty response from final LLM call")
                    
                final_result = {"llm_response": final_result}
                log_data["stages"].append({"stage": "final_response", "result": final_result})
            else:
                response_text = ""
                if isinstance(result.get('response'), dict) and 'llm_response' in result['response']:
                    response_text = result['response']['llm_response']
                elif isinstance(result.get('response'), str):
                    response_text = result['response']
                else:
                    response_text = f"Adaab! How can I help you with information about Lucknow today?"
                    
                final_result = {"llm_response": response_text}
                log_data["stages"].append({"stage": "final_response", "result": final_result})

            # Save log data
            self._save_log(log_data)

            # Cache the result with the new caching strategy
            await self._set_in_cache(query, final_result)
                
            return final_result
            
        except Exception as e:
            error_msg = f"Error processing query: {str(e)}"
            print(error_msg)
            return {
                "llm_response": "I apologize, but I encountered an error while processing your request. Please try again.",
                "error": error_msg
            }

    def _save_log(self, log_data):
        file_name = f"{log_data['uuid']}.json"
        file_path = os.path.join(self.log_folder, file_name)
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(log_data, f, indent=2, ensure_ascii=False)

    async def process_query_async(self, query, callback_url=None):
        # Submit to queue and return immediately with a request ID
        request_id = str(uuid.uuid4())
        await self.queue_client.publish(
            queue_name="query_requests",
            message={
                "request_id": request_id,
                "query": query,
                "callback_url": callback_url,
                "timestamp": datetime.now().isoformat()
            }
        )
        return {"request_id": request_id, "status": "processing"}