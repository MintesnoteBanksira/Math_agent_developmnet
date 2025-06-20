import json
from django.conf import settings
from .system_messages import CHECKER_MESSAGE
from .call_llm_clients import call_llm

def check_problem(question, answer, hints, pipeline_config):
    """
    Check if a math problem and its hints are valid using the specified model.
    
    Args:
        question (str): The math problem
        answer (str): The correct answer
        hints (dict): Dictionary of hints to validate
        pipeline_config (dict): Configuration containing provider and model information
            Example: {"provider": "openai", "model": "o3-mini"}
        
    Returns:
        tuple: (is_valid, rejection_reason, corrected_hints, cost)
    """
    try:
        # Prepare the input for the model
        input_data = {
            "problem": question,
            "answer": answer,
            "hints": hints
        }
        
        messages = [
            {"role": "system", "content": CHECKER_MESSAGE},
            {"role": "user", "content": json.dumps(input_data)}
        ]
        
        data, cost = call_llm(pipeline_config, messages)
        
        # Extract validation result
        is_valid = data.get('valid', False)
        reason = data.get('reason', '')
        corrected_hints = data.get('corrected_hints', {})
        
        return is_valid, reason, corrected_hints, cost
        
    except Exception as e:
        raise Exception(f"Error checking problem: {str(e)}") 