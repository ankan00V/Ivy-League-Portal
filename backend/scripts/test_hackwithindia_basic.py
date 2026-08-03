#!/usr/bin/env python3
"""
Basic HTTP test to check if hackwithindia.in and hackindia.org are accessible.
Tests both URLs for:
1. HTTP accessibility (status code)
2. Content availability
3. Anti-bot protection indicators
4. Hackathon/opportunity content presence
"""
import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


def create_session():
    """Create a requests session with retry logic."""
    session = requests.Session()
    retries = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"]
    )
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def test_url_scrapability(url: str, session: requests.Session) -> dict:
    """Test if a URL is scrapable and contains hackathon content."""
    result = {
        "url": url,
        "accessible": False,
        "status_code": None,
        "has_content": False,
        "has_hackathon_content": False,
        "anti_bot_detected": False,
        "scrapable": False,
        "reason": "",
        "error": None,
    }
    
    # Keywords to check for hackathon/opportunity content
    hackathon_keywords = [
        "hackathon", "hack", "competition", "event", "register",
        "participate", "prize", "challenge", "coding", "innovation",
        "opportunity", "apply", "submission", "deadline"
    ]
    
    # Anti-bot indicators
    antibot_indicators = [
        "cloudflare", "captcha", "recaptcha", "bot detection",
        "access denied", "forbidden", "please verify", "security check",
        "just a moment", "enable javascript and cookies", "checking your browser"
    ]
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    
    try:
        print(f"[HTTP] Testing {url}...")
        response = session.get(url, headers=headers, timeout=15, allow_redirects=True)
        
        result["accessible"] = True
        result["status_code"] = response.status_code
        
        # Check content
        content = response.text.lower()
        result["has_content"] = len(content.strip()) > 100
        
        # Check for hackathon content
        result["has_hackathon_content"] = any(
            keyword in content for keyword in hackathon_keywords
        )
        
        # Check for anti-bot protection
        result["anti_bot_detected"] = any(
            indicator in content for indicator in antibot_indicators
        )
        
        # Determine if scrapable
        if result["status_code"] >= 400:
            result["scrapable"] = False
            result["reason"] = f"HTTP {result['status_code']} error"
        elif result["anti_bot_detected"]:
            result["scrapable"] = False
            result["reason"] = "Anti-bot protection detected"
        elif not result["has_content"]:
            result["scrapable"] = False
            result["reason"] = "No content retrieved"
        elif not result["has_hackathon_content"]:
            result["scrapable"] = False
            result["reason"] = "No hackathon/opportunity content found"
        else:
            result["scrapable"] = True
            result["reason"] = "Successfully accessible with hackathon content"
        
    except requests.exceptions.Timeout:
        result["error"] = "Request timeout"
        result["reason"] = "Request timeout after 15 seconds"
    except requests.exceptions.ConnectionError as e:
        result["error"] = f"Connection error: {str(e)}"
        result["reason"] = "Unable to connect to server"
    except requests.exceptions.RequestException as e:
        result["error"] = f"Request error: {str(e)}"
        result["reason"] = f"Request failed: {type(e).__name__}"
    except Exception as e:
        result["error"] = f"Unexpected error: {str(e)}"
        result["reason"] = f"Unexpected error: {type(e).__name__}"
    
    return result


def main():
    """Test both URLs and report results."""
    urls = [
        "https://hackwithindia.in",
        "https://hackindia.org"
    ]
    
    print("=" * 70)
    print("Testing Website Scrapability (Basic HTTP)")
    print("=" * 70)
    print()
    
    session = create_session()
    results = []
    
    for url in urls:
        print(f"\nTesting: {url}")
        print("-" * 70)
        result = test_url_scrapability(url, session)
        results.append(result)
        
        print(f"Accessible: {result['accessible']}")
        print(f"Status Code: {result['status_code']}")
        print(f"Has Content: {result['has_content']}")
        print(f"Has Hackathon Content: {result['has_hackathon_content']}")
        print(f"Anti-bot Detected: {result['anti_bot_detected']}")
        print(f"Scrapable: {'YES' if result['scrapable'] else 'NO'}")
        print(f"Reason: {result['reason']}")
        if result['error']:
            print(f"Error: {result['error']}")
        print()
    
    # Summary
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    for result in results:
        status = "✓ YES" if result['scrapable'] else "✗ NO"
        print(f"{result['url']}: {status}")
        print(f"  Reason: {result['reason']}")
    print()


if __name__ == "__main__":
    main()

# Made with Bob
