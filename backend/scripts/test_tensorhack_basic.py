#!/usr/bin/env python3
"""
Basic HTTP test for https://tensorhack.com to evaluate scraping feasibility.
This uses only standard library and requests to avoid dependency issues.
"""
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

try:
    import requests
    from bs4 import BeautifulSoup
    HAS_DEPS = True
except ImportError:
    HAS_DEPS = False
    print("WARNING: requests or beautifulsoup4 not installed")
    print("Install with: pip install requests beautifulsoup4")


def analyze_html_content(html: str, url: str) -> dict:
    """Analyze HTML content for opportunity-related data."""
    analysis = {
        "url": url,
        "html_length": len(html),
        "has_content": len(html) > 1000,
        "keywords": {},
        "structure": {},
        "opportunities_found": [],
        "technical_details": {}
    }
    
    html_lower = html.lower()
    
    # Check for opportunity-related keywords
    opportunity_keywords = {
        "internship": html_lower.count("internship"),
        "intern": html_lower.count("intern"),
        "hackathon": html_lower.count("hackathon"),
        "fellowship": html_lower.count("fellowship"),
        "opportunity": html_lower.count("opportunity"),
        "competition": html_lower.count("competition"),
        "challenge": html_lower.count("challenge"),
    }
    analysis["keywords"]["opportunity_terms"] = opportunity_keywords
    analysis["keywords"]["total_opportunity_mentions"] = sum(opportunity_keywords.values())
    
    # Check for application-related keywords
    application_keywords = {
        "apply": html_lower.count("apply"),
        "application": html_lower.count("application"),
        "deadline": html_lower.count("deadline"),
        "eligibility": html_lower.count("eligibility"),
        "register": html_lower.count("register"),
        "registration": html_lower.count("registration"),
        "submit": html_lower.count("submit"),
    }
    analysis["keywords"]["application_terms"] = application_keywords
    analysis["keywords"]["total_application_mentions"] = sum(application_keywords.values())
    
    # Check for structured data
    analysis["structure"]["has_json_ld"] = "application/ld+json" in html_lower
    analysis["structure"]["has_schema_org"] = "schema.org" in html_lower
    analysis["structure"]["has_microdata"] = "itemtype" in html_lower or "itemprop" in html_lower
    
    # Check for common frameworks/technologies
    analysis["technical_details"]["uses_react"] = "react" in html_lower or "_next" in html_lower
    analysis["technical_details"]["uses_vue"] = "vue" in html_lower
    analysis["technical_details"]["uses_angular"] = "angular" in html_lower
    analysis["technical_details"]["is_spa"] = '<div id="root">' in html or '<div id="app">' in html
    
    # Try to parse with BeautifulSoup if available
    if HAS_DEPS:
        try:
            soup = BeautifulSoup(html, 'html.parser')
            
            # Count potential listing elements
            analysis["structure"]["div_count"] = len(soup.find_all('div'))
            analysis["structure"]["article_count"] = len(soup.find_all('article'))
            analysis["structure"]["section_count"] = len(soup.find_all('section'))
            
            # Look for title
            title_tag = soup.find('title')
            if title_tag:
                analysis["technical_details"]["page_title"] = title_tag.get_text().strip()
            
            # Look for meta description
            meta_desc = soup.find('meta', attrs={'name': 'description'})
            if meta_desc:
                analysis["technical_details"]["meta_description"] = meta_desc.get('content', '')[:200]
            
            # Look for potential opportunity listings
            # Common patterns: cards, list items with specific classes
            potential_listings = []
            
            # Look for cards or items with opportunity-related text
            for element in soup.find_all(['div', 'article', 'section', 'li']):
                text = element.get_text().lower()
                if any(keyword in text for keyword in ['internship', 'hackathon', 'fellowship', 'opportunity']):
                    if len(text) > 50 and len(text) < 1000:  # Reasonable size for a listing
                        potential_listings.append({
                            "tag": element.name,
                            "class": element.get('class', []),
                            "text_preview": element.get_text()[:150].strip()
                        })
            
            analysis["opportunities_found"] = potential_listings[:10]  # Limit to first 10
            analysis["structure"]["potential_listing_count"] = len(potential_listings)
            
        except Exception as e:
            analysis["technical_details"]["parse_error"] = str(e)
    
    return analysis


def test_tensorhack_basic():
    """Test basic HTTP access to tensorhack.com."""
    url = "https://tensorhack.com"
    
    print("=" * 80)
    print("TENSORHACK.COM BASIC HTTP SCRAPING TEST")
    print(f"Target URL: {url}")
    print("=" * 80)
    print()
    
    if not HAS_DEPS:
        print("ERROR: Required dependencies not installed")
        print("Please install: pip install requests beautifulsoup4")
        return
    
    results = {
        "url": url,
        "success": False,
        "error": None,
        "response": {},
        "analysis": {}
    }
    
    try:
        print("Sending HTTP GET request...")
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        }
        
        response = requests.get(url, headers=headers, timeout=30, allow_redirects=True)
        
        results["success"] = True
        results["response"] = {
            "status_code": response.status_code,
            "final_url": response.url,
            "headers": dict(response.headers),
            "content_length": len(response.content),
            "content_type": response.headers.get('Content-Type', ''),
            "encoding": response.encoding,
        }
        
        print(f"✓ Request successful")
        print(f"  Status Code: {response.status_code}")
        print(f"  Final URL: {response.url}")
        print(f"  Content Length: {len(response.content):,} bytes")
        print(f"  Content Type: {response.headers.get('Content-Type', 'unknown')}")
        print()
        
        # Analyze content
        print("Analyzing content...")
        analysis = analyze_html_content(response.text, url)
        results["analysis"] = analysis
        
        print()
        print("=" * 80)
        print("CONTENT ANALYSIS")
        print("=" * 80)
        print()
        
        print(f"HTML Length: {analysis['html_length']:,} characters")
        print(f"Has Substantial Content: {analysis['has_content']}")
        print()
        
        print("Opportunity Keywords Found:")
        for keyword, count in analysis["keywords"]["opportunity_terms"].items():
            if count > 0:
                print(f"  - {keyword}: {count}")
        print(f"  Total: {analysis['keywords']['total_opportunity_mentions']}")
        print()
        
        print("Application Keywords Found:")
        for keyword, count in analysis["keywords"]["application_terms"].items():
            if count > 0:
                print(f"  - {keyword}: {count}")
        print(f"  Total: {analysis['keywords']['total_application_mentions']}")
        print()
        
        print("Structured Data:")
        print(f"  - JSON-LD: {analysis['structure'].get('has_json_ld', False)}")
        print(f"  - Schema.org: {analysis['structure'].get('has_schema_org', False)}")
        print(f"  - Microdata: {analysis['structure'].get('has_microdata', False)}")
        print()
        
        print("Technical Details:")
        if 'page_title' in analysis['technical_details']:
            print(f"  - Page Title: {analysis['technical_details']['page_title']}")
        if 'meta_description' in analysis['technical_details']:
            print(f"  - Description: {analysis['technical_details']['meta_description']}")
        print(f"  - Uses React/Next.js: {analysis['technical_details'].get('uses_react', False)}")
        print(f"  - Is SPA: {analysis['technical_details'].get('is_spa', False)}")
        print()
        
        if analysis['structure'].get('potential_listing_count', 0) > 0:
            print(f"Potential Opportunity Listings Found: {analysis['structure']['potential_listing_count']}")
            print()
            print("Sample Listings (first 3):")
            for i, listing in enumerate(analysis['opportunities_found'][:3], 1):
                print(f"\n  Listing {i}:")
                print(f"    Tag: {listing['tag']}")
                print(f"    Classes: {listing['class']}")
                print(f"    Preview: {listing['text_preview'][:100]}...")
        print()
        
        # Overall assessment
        print("=" * 80)
        print("OVERALL ASSESSMENT")
        print("=" * 80)
        print()
        
        has_opportunities = analysis['keywords']['total_opportunity_mentions'] > 5
        has_applications = analysis['keywords']['total_application_mentions'] > 3
        has_listings = analysis['structure'].get('potential_listing_count', 0) > 0
        
        if response.status_code == 200:
            print("✓ SITE IS ACCESSIBLE")
            print(f"  - HTTP Status: {response.status_code}")
            print(f"  - Content Retrieved: {len(response.content):,} bytes")
        else:
            print(f"⚠ NON-200 STATUS CODE: {response.status_code}")
        print()
        
        if has_opportunities:
            print("✓ OPPORTUNITY CONTENT DETECTED")
            print(f"  - {analysis['keywords']['total_opportunity_mentions']} opportunity-related mentions")
        else:
            print("✗ LIMITED OPPORTUNITY CONTENT")
        print()
        
        if has_applications:
            print("✓ APPLICATION PROCESS INDICATORS FOUND")
            print(f"  - {analysis['keywords']['total_application_mentions']} application-related mentions")
        else:
            print("⚠ LIMITED APPLICATION INDICATORS")
        print()
        
        if has_listings:
            print(f"✓ POTENTIAL LISTINGS IDENTIFIED: {analysis['structure']['potential_listing_count']}")
        else:
            print("⚠ NO CLEAR LISTING STRUCTURE DETECTED")
        print()
        
        # Anti-bot detection
        if analysis['technical_details'].get('is_spa'):
            print("⚠ TECHNICAL CONSIDERATION: Site appears to be a Single Page Application")
            print("  - May require JavaScript rendering (Playwright/Puppeteer)")
            print("  - Static HTML scraping may not capture all content")
        print()
        
        # Final recommendation
        print("RECOMMENDATION:")
        if has_opportunities and has_applications and response.status_code == 200:
            if analysis['technical_details'].get('is_spa'):
                print("  ⚠ MODERATE CANDIDATE - Requires JavaScript Rendering")
                print("    - Site is accessible and contains opportunity content")
                print("    - Requires Playwright/Crawlee with rendering enabled")
                print("    - May need custom parsing logic")
            else:
                print("  ✓ GOOD CANDIDATE for scraper addition")
                print("    - Site is accessible")
                print("    - Contains opportunity and application content")
                print("    - Can be scraped with standard HTTP + HTML parsing")
        elif has_opportunities:
            print("  ⚠ POSSIBLE CANDIDATE - Needs Further Investigation")
            print("    - Site contains some opportunity content")
            print("    - May require custom extraction logic")
            print("    - Consider manual inspection of site structure")
        else:
            print("  ✗ NOT RECOMMENDED")
            print("    - Limited or no opportunity content detected")
            print("    - Site may not be suitable for automated scraping")
        
    except requests.exceptions.Timeout:
        results["error"] = "Request timeout"
        print("✗ REQUEST TIMEOUT")
        print("  The site took too long to respond (>30 seconds)")
    except requests.exceptions.ConnectionError as e:
        results["error"] = f"Connection error: {str(e)}"
        print("✗ CONNECTION ERROR")
        print(f"  Could not connect to the site: {str(e)}")
    except requests.exceptions.TooManyRedirects:
        results["error"] = "Too many redirects"
        print("✗ TOO MANY REDIRECTS")
        print("  The site redirected too many times")
    except Exception as e:
        results["error"] = f"{type(e).__name__}: {str(e)}"
        print(f"✗ ERROR: {type(e).__name__}")
        print(f"  {str(e)}")
    
    print()
    print("=" * 80)
    
    # Save results
    output_file = Path(__file__).parent / "tensorhack_basic_test_results.json"
    with open(output_file, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print(f"Detailed results saved to: {output_file}")
    print("=" * 80)


if __name__ == "__main__":
    test_tensorhack_basic()

# Made with Bob
