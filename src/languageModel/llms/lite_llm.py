from litellm import completion, batch_completion
import os
from typing import List, Dict, Any
import json

class LiteLLMClient:
    """
    A general-purpose class to interact with various language models using LiteLLM.
    Allows flexible model selection and configuration.
    """
    
    def __init__(self, model_name: str, api_key: str = None, base_url: str = None, **kwargs):
        """
        Initialize the LiteLLM client with a model and optional configuration.
        
        Args:
            model_name (str): Name of the model (e.g., 'gpt-3.5-turbo', 'claude-3-opus', etc.)
            api_key (str, optional): API key for the model provider
            base_url (str, optional): Custom base URL for the API (if applicable)
            **kwargs: Additional parameters for model configuration
        """
        self.model_name = model_name
        self.api_key = api_key or os.getenv("LITELLM_API_KEY")  # Fallback to env variable
        self.base_url = base_url
        self.kwargs = kwargs  # Store additional parameters like temperature, max_tokens, etc.

        # Set API key in environment if provided
        if self.api_key:
            os.environ["LITELLM_API_KEY"] = self.api_key

    async def generate_response_using_functions(self, prompt: str, functions: List[Dict], system_prompt: str = None, **call_kwargs) -> Dict:
        """
        Generate a response from the model using function calling capabilities.
        
        Args:
            prompt (str): The user's input prompt
            functions (List[Dict]): List of function definitions for the model to use
            system_prompt (str, optional): System message for context
            **call_kwargs: Additional call-specific parameters (overrides init kwargs)
        
        Returns:
            Dict: The parsed function call response
        """
        try:
            # Prepare the messages
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})

            # Merge kwargs: call-specific kwargs override initialization kwargs
            combined_kwargs = {**self.kwargs, **call_kwargs}
            combined_kwargs['functions'] = functions

            # Make the API call using LiteLLM
            response = completion(
                model=self.model_name,
                messages=messages,
                api_base=self.base_url if self.base_url else None,
                **combined_kwargs
            )

            # Extract and return the function call response
            return json.loads(response.choices[0].message.function_call.arguments)

        except Exception as e:
            print(f"Error generating response: {str(e)}")
            return {"error": f"Error generating response: {str(e)}"}
    
    async def generate_response(self, prompt: str, system_prompt: str = None, **call_kwargs) -> str:
        """
        Generate a response from the model based on a prompt.
        
        Args:
            prompt (str): The user's input prompt
            system_prompt (str, optional): System message for context
            **call_kwargs: Additional call-specific parameters (overrides init kwargs)
        
        Returns:
            str: The model's response
        """
        try:
            # Prepare the messages
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})

            # Merge kwargs: call-specific kwargs override initialization kwargs
            combined_kwargs = {**self.kwargs, **call_kwargs}

            # Make the API call using LiteLLM
            response = completion(
                model=self.model_name,
                messages=messages,
                api_base=self.base_url if self.base_url else None,
                **combined_kwargs
            )

            # Extract and return the response content
            return response.choices[0].message.content.strip()

        except Exception as e:
            return f"Error generating response: {str(e)}"
    
    
    
    async def generate_batch_responses_async(self, prompts: List[str], system_prompt: str = None, **call_kwargs) -> List[str]:
        """
        Generate responses for multiple prompts in batch.
        
        Args:
            prompts (List[str]): List of user prompts
            system_prompt (str, optional): System message for context (same for all prompts)
            **call_kwargs: Additional call-specific parameters (overrides init kwargs)
            
        Returns:
            List[str]: List of model responses in the same order as the prompts
        """
        try:
            # Prepare batch messages
            batch_messages = []
            for prompt in prompts:
                messages = []
                if system_prompt:
                    messages.append({"role": "system", "content": system_prompt})
                messages.append({"role": "user", "content": prompt})
                batch_messages.append(messages)
            
            # Merge kwargs: call-specific kwargs override initialization kwargs
            combined_kwargs = {**self.kwargs, **call_kwargs}
            
            # Make the batch API call using LiteLLM
            responses = batch_completion(
                model=self.model_name,
                messages=batch_messages,
                api_base=self.base_url if self.base_url else None,
                **combined_kwargs
            )
            
            # Extract and return the response contents
            return [response.choices[0].message.content.strip() for response in responses]
            
        except Exception as e:
            print(f"Error generating batch responses: {str(e)}")
            # Return error messages for each prompt
            return [f"Error generating response: {str(e)}"] * len(prompts)
    
    async def generate_batch_responses_async_using_functions(self, prompts: List[str], functions: List[Dict], system_prompt: str = None, **call_kwargs):
        """
        Generate responses for multiple prompts in batch with function calling support.
    
        Args:
            prompts (List[str]): List of user prompts
            functions (List[Dict]): List of function definitions
            system_prompt (str, optional): System message for context
            **call_kwargs: Additional call-specific parameters
        
        Returns:
            List[Dict]: List of complete message responses including function calls
        """
        
        try:
            batch_response = []
            for prompt in prompts: 
                messages = []
                if system_prompt:
                    messages.append({"role": "system", "content" : system_prompt})
                messages.append({"role" : "user", "content" : prompt})
                
                batch_response.append(messages)
                
            
            combined_kwargs = {**self.kwargs, **call_kwargs}
            combined_kwargs['functions']  = functions
            
            response = batch_completion(
                model = self.model_name,
                messages = batch_response,
                api_base = self.base_url if self.base_url else None,
                **combined_kwargs
            )
            return [response.choices[0].message.function_call.arguments for response in response]
        except Exception as e:
            print(f"Error generating batch responses: {str(e)}")
            # Return error messages for each prompt
            return [f"Error generating response: {str(e)}"] * len(prompts)
                    
        
    async def classify_content_using_functions(self, prompt: str, system_prompt: str = None, functions: List[Dict] = None, base64_image: str = None, **call_kwargs):
        """
        Generate a response with image classification capabilities using function calling.
        
        Args:
            prompt (str): The text prompt to accompany the image
            system_prompt (str, optional): System message for context
            functions (List[Dict]): Function definitions for the classification task
            base64_image (str): Base64-encoded image data
            **call_kwargs: Additional call-specific parameters
            
        Returns:
            Dict: The parsed function call response
        """
        try:
            # Prepare the messages with image content
            messages = []
            
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            
            # Create content array with text and image
            content = []
            content.append({"type": "text", "text": prompt})
            
            if base64_image:
                content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}
                })
            
            messages.append({"role": "user", "content": content})
            
            # Merge kwargs and add function details
            combined_kwargs = {**self.kwargs, **call_kwargs}
            if functions:
                combined_kwargs['functions'] = functions
                # If only one function, we can use function_call to force using it
                if len(functions) == 1:
                    combined_kwargs['function_call'] = {"name": functions[0]['name']}
            
            # Make the API call
            response = completion(
                model=self.model_name,
                messages=messages,
                api_base=self.base_url if self.base_url else None,
                **combined_kwargs
            )
            
            # Extract function call response
            return json.loads(response.choices[0].message.function_call.arguments)
            
        except Exception as e:
            print(f"Error in image classification: {str(e)}")
            return {"error": f"Error generating response: {str(e)}"}


    def set_model(self, new_model_name: str):
        """
        Change the model being used by the client.
        
        Args:
            new_model_name (str): The new model name to use
        """
        self.model_name = new_model_name

    def update_config(self, **new_kwargs):
        """
        Update the configuration parameters for the model.
        
        Args:
            **new_kwargs: New configuration parameters to update
        """
        self.kwargs.update(new_kwargs)


# Example usage
# if __name__ == "__main__":
#     # Initialize the client with a model (e.g., OpenAI's GPT-3.5-turbo)
#     client = LiteLLMClient(
#         model_name="gpt-3.5-turbo",
#         api_key="your-api-key-here",
#         temperature=0.7,
#         max_tokens=150
#     )

#     # Generate a response
#     prompt = "Write a short poem about the moon."
#     system_prompt = "You are a creative poet."
#     response = client.generate_response(prompt, system_prompt)
#     print("Response:", response)

#     # Generate batch responses
#     prompts = [
#         "Write a short poem about the moon.",
#         "Explain quantum computing in simple terms.",
#         "What are the benefits of regular exercise?"
#     ]
#     responses = client.generate_batch_responses(prompts, system_prompt)
#     for i, response in enumerate(responses):
#         print(f"Response {i+1}:", response)

#     # Switch model (e.g., to Anthropic's Claude)
#     client.set_model("claude-3-opus")
#     response = client.generate_response(prompt, system_prompt, temperature=0.9)
#     print("Claude Response:", response)

#     # Update configuration
#     client.update_config(max_tokens=200)
#     response = client.generate_response(prompt)
#     print("Updated Response:", response)