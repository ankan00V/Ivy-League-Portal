#!/usr/bin/env python3
"""
Test script to check if hackwithindia.in and hackindia.org are scrapable.
Tests both URLs for:
1. HTTP accessibility
2. Content availability
3. Anti-bot protection
4. Hackathon/opportunity content presence
"""
import asyncio
import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.firecrawl_client import firecrawl_client, FirecrawlUnavailableError
from app.services.crawlee_client import crawlee_client, CrawleeUnavailableError


async def test_url_scrapability(url: str) -> dict:
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
        "provider_used": None,
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
        "just a moment", "enable javascript and cookies"
    ]
    
    # Try Firecrawl first
    if firecrawl_client.configured:
        try:
            print(f"[Firecrawl] Testing {url}...")
            fetch_result = await firecrawl_client.scrape(url, timeout_seconds=15.0)
            result["accessible"] = True
            result["status_code"] = fetch_result.status_code
            result["provider_used"] = "firecrawl"
            
            # Check content
            content = (fetch_result.html + " " + fetch_result.markdown).lower()
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
                result["reason"] = "Successfully scraped with hackathon content"
            
            return result
            
        except FirecrawlUnavailableError as e:
            result["error"] = f"Firecrawl error: {str(e)}"
            print(f"[Firecrawl] Failed: {e}")
        except Exception as e:
            result["error"] = f"Firecrawl exception: {str(e)}"
            print(f"[Firecrawl] Exception: {e}")
    
    # Try Crawlee as fallback
    if crawlee_client.configured:
        try:
            print(f"[Crawlee] Testing {url}...")
            fetch_result = await crawlee_client.scrape(url, render=True, timeout_seconds=15.0)
            result["accessible"] = True
            result["status_code"] = fetch_result.status_code
            result["provider_used"] = "crawlee"
            
            # Check content
            content = fetch_result.html.lower()
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
                result["reason"] = "Successfully scraped with hackathon content"
            
            return result
            
        except CrawleeUnavailableError as e:
            result["error"] = f"Crawlee error: {str(e)}"
            print(f"[Crawlee] Failed: {e}")
        except Exception as e:
            result["error"] = f"Crawlee exception: {str(e)}"
            print(f"[Crawlee] Exception: {e}")
    
    # If both failed
    if not result["accessible"]:
        result["scrapable"] = False
        result["reason"] = result["error"] or "No scraping service available"
    
    return result


async def main():
    """Test both URLs and report results."""
    urls = [
        "https://hackwithindia.in",
        "https://hackindia.org"
    ]
    
    print("=" * 70)
    print("Testing Website Scrapability")
    print("=" * 70)
    print()
    
    results = []
    for url in urls:
        print(f"\nTesting: {url}")
        print("-" * 70)
        result = await test_url_scrapability(url)
        results.append(result)
        
        print(f"Provider: {result['provider_used'] or 'None'}")
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
    asyncio.run(main())

# Made with Bob
