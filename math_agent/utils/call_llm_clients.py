import openai
import google.generativeai as genai
from django.conf import settings
import json
import re
from .LLM_cost import calculate_cost

def safe_json_parse(raw_text):
    """Parse JSON from model response, handling common formatting issues."""
    raw_text = raw_text.strip()
    if raw_text.startswith("```json"):
        raw_text = raw_text[7:]
    elif raw_text.startswith("```"):
        raw_text = raw_text[3:]
    if raw_text.endswith("```"):
        raw_text = raw_text[:-3]

    # Fix LaTeX-style escapes
    raw_text = re.sub(r'(?<!\\)\\(?![\\nt"\\/bfr])', r'\\\\', raw_text)

    try:
        return json.loads(raw_text)
    except json.JSONDecodeError as e:
        print("⚠️ JSON decode error at char", e.pos)
        print("Offending text:\n", raw_text[e.pos-50:e.pos+50])
        raise ValueError(f"Model output is not valid JSON: {e}")

def call_llm(pipeline_config, messages):
    """
    Make a call to the specified LLM provider and model.
    
    Args:
        pipeline_config (dict): Configuration containing provider and model information
            Example: {"provider": "openai", "model": "o3-mini"}
        messages (list): List of message dictionaries with 'role' and 'content'
        
    Returns:
        tuple: (parsed_response, cost)
            - parsed_response (dict): The parsed JSON response from the model
            - cost (float): The calculated cost for this API call
    """
    try:
        provider = pipeline_config['provider'].lower()
        model = pipeline_config['model']
        
        if provider == 'openai':
            client = openai.OpenAI(api_key=settings.OPENAI_API_KEY)
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=1.0
            )
            raw_response = response.choices[0].message.content.strip()
            input_tokens = response.usage.prompt_tokens
            output_tokens = response.usage.completion_tokens
            
        elif provider == 'google':
            genai.configure(api_key=settings.GOOGLE_API_KEY)
            model_instance = genai.GenerativeModel(model)
            # Convert messages to a single prompt for Gemini
            prompt = "\n".join([msg["content"] for msg in messages])
            response = model_instance.generate_content(prompt)
            raw_response = response.text.strip()
            input_tokens = response.prompt_token_count
            output_tokens = response.candidates[0].token_count
            
        else:
            raise ValueError(f"Unsupported provider: {provider}")
        
        # Calculate cost using LLM_cost utility
        cost = calculate_cost(
            provider=provider,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens
        )
        
        # Parse and return both response and cost
        return safe_json_parse(raw_response), cost
            
    except Exception as e:
        raise Exception(f"Error calling LLM: {str(e)}")

# Example usage:
if __name__ == "__main__":
    # Example messages
    messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Hello, how are you?"}
    ]
    
    # Example calls
    try:
        # OpenAI call
        openai_config = {"provider": "openai", "model": "o3-mini"}
        response, cost = call_llm(openai_config, messages)
        print("OpenAI Response:", response)
        print("Cost: $", cost)
        
        # Google call
        google_config = {"provider": "google", "model": "gemini-2.5-pro"}
        response, cost = call_llm(google_config, messages)
        print("Google Response:", response)
        print("Cost: $", cost)
        
    except Exception as e:
        print(f"Error: {str(e)}") 