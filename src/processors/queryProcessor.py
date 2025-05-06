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

class QueryProcessor:
    def __init__(self, log_folder="query_logs"):
        self.max_tokens = 16000  # Max tokens for API call
        self.input_token_limit = 16384
        self.temperature = 0.5
        self.top_p = 0.9
        self.lite_llm_handler = LiteLLMClient(api_key=Settings.GEMINI_API_KEY, model_name="gemini-2.0-flash-lite")
        self.api_handler = APIHandler()
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
    
    async def process_query(self, query):
        log_data = {
            "uuid": str(uuid.uuid4()),
            "timestamp": datetime.now().isoformat(),
            "query": query,
            "stages": []
        }

        combined_prompt = TRANSLATION_USER_PROMPT + "\n" + query + "\n Output in JSON format:"
        # print(combined_prompt)
        
        # First stage: Translate and determine if API is needed
        result = await self.lite_llm_handler.generate_response(
            combined_prompt 
        )
        # print(result)
        
        log_data["stages"].append({"stage": "translation", "result": result})
        result = self.extract_json_string(result)
        if result["api_needed"] == 1:
            # Second stage: Process with API
            # print("Under API Needed ", result)
            result_api = await self.api_handler.process_input(result)
            final_api_output = {"User Query": query, "api_results": result_api}
            log_data["stages"].append({"stage": "api_processing", "result": result_api})

            # Third stage: Generate final response
            
            combined_final_prompt = RESPONSE_USER_PROMPT + "\n" + str(final_api_output) + "\n Output in Markdown format:"
            final_result = await self.lite_llm_handler.generate_response(
                combined_final_prompt
            )
            final_result = {"llm_response": final_result}
            log_data["stages"].append({"stage": "final_response", "result": final_result})
        else:
            # print("Under API Not Needed ", result)
            # If API is not needed, use the response directly
            final_result = {"llm_response": result['response']}
            log_data["stages"].append({"stage": "final_response", "result": final_result})

        # Save log data
        self._save_log(log_data)

        return final_result

    def _save_log(self, log_data):
        file_name = f"{log_data['uuid']}.json"
        file_path = os.path.join(self.log_folder, file_name)
        with open(file_path, 'w') as f:
            json.dump(log_data, f, indent=2)