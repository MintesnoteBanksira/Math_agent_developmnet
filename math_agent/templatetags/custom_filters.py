from django import template
register = template.Library()
 
@register.filter
def dict_get(d, key):
    if isinstance(d, dict):
        return d.get(str(key)) or d.get(int(key))
    return None 