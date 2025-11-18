"""
Service to detect if user wants media search based on message content
"""
from typing import Dict


def should_search_media(message: str) -> Dict[str, bool]:
    """
    Detect if user explicitly requests YouTube or web search
    
    Args:
        message: User's message text
        
    Returns:
        {
            'youtube': bool,  # Should search YouTube
            'web': bool,      # Should search web
            'triggered': bool # Any search triggered
        }
    """
    message_lower = message.lower()
    
    # YouTube search triggers
    youtube_triggers = [
        'find youtube', 'search youtube', 'youtube video',
        'show me videos', 'find videos', 'video tutorial',
        'watch video', 'youtube tutorial', 'find tutorial',
        'show tutorial', 'video about', 'videos about',
        'youtube search', 'look for video', 'get video'
    ]
    
    # Web search triggers
    web_triggers = [
        'find article', 'search web', 'web article',
        'find blog', 'search article', 'show me article',
        'web resource', 'read article', 'web search',
        'look for article', 'get article', 'find documentation',
        'search documentation', 'web resource'
    ]
    
    # Check for triggers
    search_youtube = any(trigger in message_lower for trigger in youtube_triggers)
    search_web = any(trigger in message_lower for trigger in web_triggers)
    
    # Special case: "find both" or "search everything"
    both_triggers = ['find both', 'search everything', 'search all', 'find all resources']
    if any(trigger in message_lower for trigger in both_triggers):
        search_youtube = True
        search_web = True
    
    return {
        'youtube': search_youtube,
        'web': search_web,
        'triggered': search_youtube or search_web
    }


def extract_search_query(message: str) -> str:
    """
    Extract the actual search query from user message
    
    Example:
        "find youtube videos about React hooks" -> "React hooks"
        "search web for Python tutorials" -> "Python tutorials"
    """
    message = message.strip()
    
    # Remove trigger phrases
    triggers = [
        'find youtube videos about', 'search youtube for',
        'find videos about', 'show me videos about',
        'find article about', 'search web for',
        'find both about', 'search everything about',
        'youtube search:', 'web search:'
    ]
    
    message_lower = message.lower()
    for trigger in triggers:
        if trigger in message_lower:
            # Find position and extract after it
            pos = message_lower.find(trigger)
            query = message[pos + len(trigger):].strip()
            return query
    
    # If no trigger found, return original message
    return message
