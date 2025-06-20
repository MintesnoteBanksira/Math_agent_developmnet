import json
from django.conf import settings
from .system_messages import TARGET_MESSAGE
from .call_llm_clients import call_llm

def test_with_target(question, pipeline_config):
    """
    Test a math problem with the target model.
    
    Args:
        question (str): The math problem
        pipeline_config (dict): Configuration containing provider and model information
            Example: {"provider": "openai", "model": "o3-mini"}
        
    Returns:
        tuple: (answer, cost)
    """
    try:
        # Prepare the input for the model
        input_data = {
            "problem": question
        }
        
        messages = [
            {"role": "system", "content": TARGET_MESSAGE},
            {"role": "user", "content": json.dumps(input_data)}
        ]
        
        data, cost = call_llm(pipeline_config, messages)
        
        # Handle different response formats
        answer = None
        
        # Try to extract answer from JSON response
        if isinstance(data, dict):
            answer = data.get('answer', '')
        elif isinstance(data, str):
            # If the response is a string, try to parse it as JSON
            try:
                parsed_data = json.loads(data)
                if isinstance(parsed_data, dict):
                    answer = parsed_data.get('answer', '')
                else:
                    answer = str(parsed_data)
            except json.JSONDecodeError:
                # If it's not JSON, treat the entire response as the answer
                answer = data
        else:
            # For any other type, convert to string
            answer = str(data)
        
        if not answer:
            raise ValueError("Invalid response: missing or empty answer")
        
        # Ensure answer is a string and strip whitespace
        answer = str(answer).strip()
        
        return answer, cost
        
    except Exception as e:
        raise Exception(f"Error testing with target model: {str(e)}") 