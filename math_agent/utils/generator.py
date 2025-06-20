import json
from django.conf import settings
from .system_messages import GENERATOR_MESSAGE
from .call_llm_clients import call_llm
from .similarity_utils import find_similar_problems

def generate_problem(pipeline_config, taxonomy=None):
    """
    Generate a math problem using the specified model.
    
    Args:
        pipeline_config (dict): Configuration containing provider and model information
            Example: {"provider": "openai", "model": "o3-mini"}
        taxonomy (dict, optional): Dictionary containing subject and topic
        
    Returns:
        tuple: (question, answer, hints, embedding, similar_problems, cost)
    """
    try:
        # Prepare the prompt based on taxonomy
        user_prompt = "Generate a new problem as instructed."
        if taxonomy:
            subject = taxonomy.get('subject', '')
            topic = taxonomy.get('topic', '')
            user_prompt = f"Generate a math problem in {subject} under the topic '{topic}'."
        
        messages = [
            {"role": "system", "content": GENERATOR_MESSAGE},
            {"role": "user", "content": user_prompt}
        ]
        
        # Call the model using our centralized client
        data, cost = call_llm(pipeline_config, messages)
        
        # Extract question, answer, and hints
        question = data.get('problem', '')
        answer = data.get('answer', '')
        hints = data.get('hints', {})
        
        if not question or not answer or not hints:
            raise ValueError("Invalid response: missing problem, answer, or hints")
        
        # Similarity check
        similar_problems, embedding = find_similar_problems(question)
        
        return question, answer, hints, embedding, similar_problems, cost
        
    except Exception as e:
        raise Exception(f"Error generating problem: {str(e)}") 