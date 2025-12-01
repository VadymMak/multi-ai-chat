"""
Git Service Layer
Handles Git repository integration: URL normalization, validation, and structure reading via GitHub API
"""

import re
import logging
from typing import Tuple, List, Dict, Optional
import requests

logger = logging.getLogger(__name__)


def normalize_git_url(url: str) -> str:
    """
    Normalize Git URL to canonical format: "github.com/user/repo"
    
    Supports various formats:
    - https://github.com/user/repo
    - https://github.com/user/repo.git
    - git@github.com:user/repo.git
    - github.com/user/repo
    - https://gitlab.com/user/repo
    - https://bitbucket.org/user/repo
    
    Args:
        url: Git repository URL in any format
        
    Returns:
        Normalized URL: "github.com/user/repo"
        
    Raises:
        ValueError: If URL format is invalid
        
    Examples:
        >>> normalize_git_url("https://github.com/user/repo")
        "github.com/user/repo"
        
        >>> normalize_git_url("git@github.com:user/repo.git")
        "github.com/user/repo"
    """
    if not url or not isinstance(url, str):
        raise ValueError("URL must be a non-empty string")
    
    url = url.strip()
    
    # Remove .git suffix if present
    if url.endswith('.git'):
        url = url[:-4]
    
    # Pattern 1: HTTPS format - https://github.com/user/repo
    https_pattern = r'https?://([^/]+)/([^/]+)/([^/]+)'
    match = re.match(https_pattern, url)
    if match:
        domain, owner, repo = match.groups()
        return f"{domain}/{owner}/{repo}"
    
    # Pattern 2: SSH format - git@github.com:user/repo
    ssh_pattern = r'git@([^:]+):([^/]+)/(.+)'
    match = re.match(ssh_pattern, url)
    if match:
        domain, owner, repo = match.groups()
        return f"{domain}/{owner}/{repo}"
    
    # Pattern 3: Already normalized - github.com/user/repo
    normalized_pattern = r'([^/]+)/([^/]+)/([^/]+)'
    match = re.match(normalized_pattern, url)
    if match:
        domain, owner, repo = match.groups()
        # Validate domain
        if domain not in ['github.com', 'gitlab.com', 'bitbucket.org']:
            raise ValueError(f"Unsupported Git provider: {domain}. Supported: github.com, gitlab.com, bitbucket.org")
        return url
    
    raise ValueError(
        "Invalid Git URL format. Supported formats:\n"
        "  - https://github.com/user/repo\n"
        "  - git@github.com:user/repo.git\n"
        "  - github.com/user/repo"
    )


def parse_github_url(git_url: str) -> Tuple[str, str]:
    """
    Parse normalized Git URL to extract owner and repo
    
    Args:
        git_url: Normalized Git URL (e.g., "github.com/user/repo")
        
    Returns:
        Tuple of (owner, repo)
        
    Raises:
        ValueError: If URL cannot be parsed
        
    Examples:
        >>> parse_github_url("github.com/VadymMak/multi-ai-chat")
        ("VadymMak", "multi-ai-chat")
    """
    if not git_url or not isinstance(git_url, str):
        raise ValueError("git_url must be a non-empty string")
    
    parts = git_url.split('/')
    
    if len(parts) != 3:
        raise ValueError(f"Invalid normalized Git URL: {git_url}. Expected format: domain/owner/repo")
    
    domain, owner, repo = parts
    
    if not owner or not repo:
        raise ValueError(f"Invalid Git URL: owner and repo cannot be empty")
    
    return owner, repo


def validate_repo_exists(git_url: str) -> Tuple[bool, Optional[str]]:
    """
    Quick check if repository exists and is accessible
    
    Args:
        git_url: Normalized Git URL (e.g., "github.com/user/repo")
        
    Returns:
        Tuple of (success: bool, error_message: Optional[str])
        
    Examples:
        >>> validate_repo_exists("github.com/VadymMak/multi-ai-chat")
        (True, None)
        
        >>> validate_repo_exists("github.com/user/nonexistent")
        (False, "Repository not found (404)")
    """
    try:
        # Parse URL
        owner, repo = parse_github_url(git_url)
        
        # Only GitHub is supported for now
        if not git_url.startswith('github.com'):
            return False, "Only GitHub repositories are supported"
        
        # Make HEAD request to check if repo exists
        api_url = f"https://api.github.com/repos/{owner}/{repo}"
        
        logger.info(f"Validating repository: {api_url}")
        
        response = requests.head(
            api_url,
            timeout=10,
            headers={'Accept': 'application/vnd.github.v3+json'}
        )
        
        if response.status_code == 200:
            logger.info(f"✅ Repository exists: {git_url}")
            return True, None
        elif response.status_code == 404:
            error_msg = "Repository not found (404)"
            logger.warning(f"❌ {error_msg}: {git_url}")
            return False, error_msg
        elif response.status_code == 403:
            error_msg = "GitHub API rate limit exceeded (403)"
            logger.warning(f"⚠️ {error_msg}")
            return False, error_msg
        elif response.status_code == 401:
            error_msg = "Repository is private and requires authentication (401)"
            logger.warning(f"🔒 {error_msg}: {git_url}")
            return False, error_msg
        else:
            error_msg = f"Unexpected response ({response.status_code})"
            logger.error(f"❌ {error_msg}: {git_url}")
            return False, error_msg
            
    except requests.exceptions.Timeout:
        error_msg = "Request timeout - GitHub API not responding"
        logger.error(f"⏱️ {error_msg}")
        return False, error_msg
    except requests.exceptions.ConnectionError:
        error_msg = "Network error - cannot reach GitHub API"
        logger.error(f"🌐 {error_msg}")
        return False, error_msg
    except Exception as e:
        error_msg = f"Validation error: {str(e)}"
        logger.exception(f"❌ {error_msg}")
        return False, error_msg


def read_github_structure(git_url: str, branch: str = "main") -> List[Dict[str, any]]:
    """
    Read repository file structure via GitHub API
    
    Args:
        git_url: Normalized Git URL (e.g., "github.com/user/repo")
        branch: Branch name (default: "main", fallback to "master")
        
    Returns:
        List of file dictionaries with 'path', 'type', 'size'
        
    Raises:
        ValueError: If URL is invalid
        requests.HTTPError: If API request fails
        
    Examples:
        >>> files = read_github_structure("github.com/VadymMak/multi-ai-chat")
        >>> files[0]
        {'path': 'backend/app/main.py', 'type': 'file', 'size': 5420}
    """
    # Parse URL
    owner, repo = parse_github_url(git_url)
    
    # Only GitHub is supported
    if not git_url.startswith('github.com'):
        raise ValueError("Only GitHub repositories are supported")
    
    # Try main branch first, fallback to master
    branches_to_try = [branch]
    if branch == "main":
        branches_to_try.append("master")
    
    last_error = None
    
    for branch_name in branches_to_try:
        try:
            api_url = f"https://api.github.com/repos/{owner}/{repo}/git/trees/{branch_name}?recursive=1"
            
            logger.info(f"Reading repository structure: {api_url}")
            
            response = requests.get(
                api_url,
                timeout=30,
                headers={'Accept': 'application/vnd.github.v3+json'}
            )
            
            # Check response
            if response.status_code == 200:
                data = response.json()
                tree = data.get('tree', [])
                
                # Filter only files (exclude directories)
                files = [
                    {
                        'path': item['path'],
                        'type': item['type'],
                        'size': item.get('size', 0)
                    }
                    for item in tree
                    if item['type'] == 'blob'  # blob = file, tree = directory
                ]
                
                logger.info(f"✅ Successfully read {len(files)} files from {git_url} (branch: {branch_name})")
                return files
                
            elif response.status_code == 404:
                last_error = f"Branch '{branch_name}' not found"
                logger.warning(f"⚠️ {last_error}")
                continue  # Try next branch
                
            elif response.status_code == 403:
                # Rate limit or private repo
                error_data = response.json()
                if 'rate limit' in error_data.get('message', '').lower():
                    remaining = response.headers.get('X-RateLimit-Remaining', '0')
                    reset_time = response.headers.get('X-RateLimit-Reset', 'unknown')
                    raise requests.HTTPError(
                        f"GitHub API rate limit exceeded. "
                        f"Remaining: {remaining}. "
                        f"Resets at: {reset_time}"
                    )
                else:
                    raise requests.HTTPError("Repository is private. Public repositories only.")
                    
            else:
                raise requests.HTTPError(f"GitHub API error: {response.status_code} - {response.text}")
                
        except requests.exceptions.Timeout:
            raise requests.HTTPError("Request timeout - GitHub API not responding")
        except requests.exceptions.ConnectionError:
            raise requests.HTTPError("Network error - cannot reach GitHub API")
    
    # If we get here, all branches failed
    raise requests.HTTPError(f"Repository structure could not be read. {last_error}")


# ===== Example Usage (for testing) =====

if __name__ == "__main__":
    # Test normalization
    test_urls = [
        "https://github.com/VadymMak/multi-ai-chat",
        "git@github.com:VadymMak/multi-ai-chat.git",
        "github.com/VadymMak/multi-ai-chat",
    ]
    
    print("=== Testing URL Normalization ===")
    for url in test_urls:
        try:
            normalized = normalize_git_url(url)
            print(f"✅ {url}\n   → {normalized}\n")
        except ValueError as e:
            print(f"❌ {url}\n   → Error: {e}\n")
    
    # Test validation
    print("\n=== Testing Repository Validation ===")
    test_repo = "github.com/torvalds/linux"  # Public repo that definitely exists
    success, error = validate_repo_exists(test_repo)
    if success:
        print(f"✅ {test_repo} - Repository exists!")
    else:
        print(f"❌ {test_repo} - Error: {error}")
    
    # Test structure reading (commented out to avoid API calls)
    # print("\n=== Testing Structure Reading ===")
    # try:
    #     files = read_github_structure("github.com/VadymMak/multi-ai-chat")
    #     print(f"✅ Found {len(files)} files")
    #     print("First 5 files:")
    #     for f in files[:5]:
    #         print(f"  - {f['path']} ({f['size']} bytes)")
    # except Exception as e:
    #     print(f"❌ Error: {e}")