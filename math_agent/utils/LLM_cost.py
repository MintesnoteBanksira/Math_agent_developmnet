# Only includes the specified models with their pricing
PROVIDER_COSTS = {
    "openai": {
        "models": {
            "o3-mini": {
                "input_per_million": 1.10,
                "cached_input_per_million": 0.55,
                "output_per_million": 4.40
            },
            "gpt-4.1-mini": {
                "input_per_million": 0.40,
                "cached_input_per_million": 0.10,
                "output_per_million": 1.60
            },
            "gpt-4.1": {
                "input_per_million": 2.00,
                "cached_input_per_million": 0.50,
                "output_per_million": 8.00
            },
            "o3": {
                "input_per_million": 2.00,
                "cached_input_per_million": 0.50,
                "output_per_million": 8.00
            },
            "o4-mini": {
                "input_per_million": 1.10,
                "cached_input_per_million": 0.275,
                "output_per_million": 4.40
            }
        }
    },
    "google": {
        "models": {
            "gemini-2.5-pro": {
                "input_per_million": 1.25,
                "output_per_million": 10.00
            },
            "gemini-2.5-flash": {
                "input_per_million": 0.50,
                "output_per_million": 2.50,
                "cache_per_million": 0.075
            }
        }
    }
}

def calculate_cost(provider: str, model: str, input_tokens: int, output_tokens: int, use_cache: bool = False, cached_input_tokens: int = 0) -> float:
    """
    Calculate the cost for a specific model usage.
    
    Args:
        provider (str): The provider name (e.g., 'openai', 'google')
        model (str): The model name
        input_tokens (int): Number of input/prompt tokens
        output_tokens (int): Number of output/completion tokens
        use_cache (bool): Whether to include context caching cost (Gemini Flash only)
        cached_input_tokens (int): Number of cached input tokens (OpenAI only)
    
    Returns:
        float: Total cost in USD
    """
    try:
        model_costs = PROVIDER_COSTS[provider]["models"][model]
        
        # Calculate input cost
        input_cost = (input_tokens - cached_input_tokens) * (model_costs.get("input_per_million", 0) / 1_000_000)
        cached_input_cost = cached_input_tokens * (model_costs.get("cached_input_per_million", 0) / 1_000_000)
        output_cost = output_tokens * (model_costs["output_per_million"] / 1_000_000)
        total_cost = input_cost + cached_input_cost + output_cost
        
        # Add caching cost for Gemini Flash if requested
        if use_cache and provider == "google" and model == "gemini-2.5-flash":
            total_tokens = input_tokens + output_tokens
            cache_cost = total_tokens * (model_costs["cache_per_million"] / 1_000_000)
            total_cost += cache_cost
        
        return total_cost
    except KeyError:
        raise ValueError(f"Provider '{provider}' or model '{model}' not found in pricing data") 