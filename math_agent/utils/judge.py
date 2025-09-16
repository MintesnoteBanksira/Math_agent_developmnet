import json
from django.conf import settings
from .system_messages import JUDGE_MESSAGE, JUDGE_MCQ_MESSAGE
from .call_llm_clients import call_llm

def judge_solution(target_solution, true_answer, pipeline_config, mcq_mode=False, problem_text=""):
    """
    Judge if the target model's solution is correct by comparing it with the true answer.
    
    Args:
        target_solution (str): The target model's solution attempt
        true_answer (str): The correct answer that passed the checker
        pipeline_config (dict): Configuration containing provider and model information
            Example: {"provider": "openai", "model": "o3-mini"}
        
    Returns:
        tuple: (is_valid, cost)
    """
    try:
        # Choose system message based on MCQ mode
        system_message = JUDGE_MCQ_MESSAGE if mcq_mode else JUDGE_MESSAGE
        
        # Prepare the input for the model
        input_data = {
            "true_answer": true_answer,
            "model_answer": target_solution
        }
        
        # Add problem text for MCQ mode
        if mcq_mode and problem_text:
            input_data["problem_text"] = problem_text
        
        messages = [
            {"role": "system", "content": system_message},
            {"role": "user", "content": json.dumps(input_data)}
        ]
        
        data, cost = call_llm(pipeline_config, messages)
        
        # Extract validation result
        is_valid = data.get('valid', False)
        reason = data.get('reason', '')
        
        if reason:
            print(f"Judge reason: {reason}")
            
        return is_valid, cost
        
    except Exception as e:
        raise Exception(f"Error judging solution: {str(e)}") 