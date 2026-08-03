#!/usr/bin/env python3
"""
Test script to evaluate scraping capabilities for https://tensorhack.com
This script tests both Firecrawl and Crawlee clients to determine if the site
can be scraped for internship and opportunity data.
"""
import asyncio
import json
import logging
import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.firecrawl_client import firecrawl_client, FirecrawlUnavailableError
from app.services.crawlee_client import crawlee_client, CrawleeUnavailableError

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


async def test_firecrawl_scrape(url: str) -> dict:
    """Test Firecrawl scraping capabilities."""
    result = {
        "client": "firecrawl",
        "url": url,
        "success": False,
        "error": None,
        "data": None,
        "analysis": {}
    }
    
    try:
        logger.info(f"Testing Firecrawl scrape for {url}")
        
        if not firecrawl_client.configured:
            result["error"] = "Firecrawl client not configured"
            result["analysis"]["configured"] = False
            return result
        
        result["analysis"]["configured"] = True
        
        fetch_result = await firecrawl_client.scrape(url, timeout_seconds=30.0)
        
        result["success"] = True
        result["data"] = {
            "final_url": fetch_result.final_url,
            "status_code": fetch_result.status_code,
            "elapsed_seconds": fetch_result.elapsed_seconds,
            "html_length": len(fetch_result.html),
            "markdown_length": len(fetch_result.markdown),
            "metadata": fetch_result.metadata,
            "html_preview": fetch_result.html[:500] if fetch_result.html else None,
            "markdown_preview": fetch_result.markdown[:1000] if fetch_result.markdown else None,
        }
        
        # Analyze content for opportunities
        markdown_lower = fetch_result.markdown.lower()
        html_lower = fetch_result.html.lower()
        
        result["analysis"]["has_internship_keywords"] = any(
            keyword in markdown_lower or keyword in html_lower
            for keyword in ["internship", "intern", "opportunity", "hackathon", "fellowship"]
        )
        
        result["analysis"]["has_application_keywords"] = any(
            keyword in markdown_lower or keyword in html_lower
            for keyword in ["apply", "application", "deadline", "eligibility", "register"]
        )
        
        result["analysis"]["has_structured_data"] = any(
            keyword in html_lower
            for keyword in ["json-ld", "schema.org", "itemtype", "microdata"]
        )
        
        # Check for common listing patterns
        result["analysis"]["potential_listing_count"] = (
            markdown_lower.count("deadline") + 
            markdown_lower.count("apply now") +
            markdown_lower.count("eligibility")
        )
        
        logger.info(f"Firecrawl scrape successful: {fetch_result.status_code}, {len(fetch_result.markdown)} chars")
        
    except FirecrawlUnavailableError as e:
        result["error"] = f"FirecrawlUnavailableError: {str(e)}"
        logger.error(f"Firecrawl unavailable: {e}")
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {str(e)}"
        logger.error(f"Firecrawl error: {e}", exc_info=True)
    
    return result


async def test_crawlee_scrape(url: str, render: bool = False) -> dict:
    """Test Crawlee scraping capabilities."""
    result = {
        "client": "crawlee",
        "url": url,
        "render": render,
        "success": False,
        "error": None,
        "data": None,
        "analysis": {}
    }
    
    try:
        logger.info(f"Testing Crawlee scrape for {url} (render={render})")
        
        if not crawlee_client.configured:
            result["error"] = "Crawlee client not configured"
            result["analysis"]["configured"] = False
            return result
        
        result["analysis"]["configured"] = True
        
        fetch_result = await crawlee_client.scrape(url, render=render, timeout_seconds=30.0)
        
        result["success"] = True
        result["data"] = {
            "final_url": fetch_result.final_url,
            "status_code": fetch_result.status_code,
            "elapsed_seconds": fetch_result.elapsed_seconds,
            "html_length": len(fetch_result.html),
            "metadata": fetch_result.metadata,
            "html_preview": fetch_result.html[:500] if fetch_result.html else None,
        }
        
        # Analyze content for opportunities
        html_lower = fetch_result.html.lower()
        
        result["analysis"]["has_internship_keywords"] = any(
            keyword in html_lower
            for keyword in ["internship", "intern", "opportunity", "hackathon", "fellowship"]
        )
        
        result["analysis"]["has_application_keywords"] = any(
            keyword in html_lower
            for keyword in ["apply", "application", "deadline", "eligibility", "register"]
        )
        
        result["analysis"]["has_structured_data"] = any(
            keyword in html_lower
            for keyword in ["json-ld", "schema.org", "itemtype", "microdata"]
        )
        
        # Check for common listing patterns
        result["analysis"]["potential_listing_count"] = (
            html_lower.count("deadline") + 
            html_lower.count("apply now") +
            html_lower.count("eligibility")
        )
        
        logger.info(f"Crawlee scrape successful: {fetch_result.status_code}, {len(fetch_result.html)} chars")
        
    except CrawleeUnavailableError as e:
        result["error"] = f"CrawleeUnavailableError: {str(e)}"
        logger.error(f"Crawlee unavailable: {e}")
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {str(e)}"
        logger.error(f"Crawlee error: {e}", exc_info=True)
    
    return result


async def main():
    """Run all scraping tests and generate report."""
    url = "https://tensorhack.com"
    
    print("=" * 80)
    print(f"TENSORHACK.COM SCRAPING CAPABILITY TEST")
    print(f"Target URL: {url}")
    print("=" * 80)
    print()
    
    results = []
    
    # Test Firecrawl
    print("Testing Firecrawl client...")
    firecrawl_result = await test_firecrawl_scrape(url)
    results.append(firecrawl_result)
    print(f"  Status: {'✓ SUCCESS' if firecrawl_result['success'] else '✗ FAILED'}")
    if firecrawl_result['error']:
        print(f"  Error: {firecrawl_result['error']}")
    print()
    
    # Test Crawlee (BeautifulSoup)
    print("Testing Crawlee client (BeautifulSoup)...")
    crawlee_bs_result = await test_crawlee_scrape(url, render=False)
    results.append(crawlee_bs_result)
    print(f"  Status: {'✓ SUCCESS' if crawlee_bs_result['success'] else '✗ FAILED'}")
    if crawlee_bs_result['error']:
        print(f"  Error: {crawlee_bs_result['error']}")
    print()
    
    # Test Crawlee (Playwright)
    print("Testing Crawlee client (Playwright)...")
    crawlee_pw_result = await test_crawlee_scrape(url, render=True)
    results.append(crawlee_pw_result)
    print(f"  Status: {'✓ SUCCESS' if crawlee_pw_result['success'] else '✗ FAILED'}")
    if crawlee_pw_result['error']:
        print(f"  Error: {crawlee_pw_result['error']}")
    print()
    
    # Generate detailed report
    print("=" * 80)
    print("DETAILED ANALYSIS REPORT")
    print("=" * 80)
    print()
    
    for result in results:
        if result['success']:
            print(f"Client: {result['client']}" + (f" (render={result.get('render')})" if 'render' in result else ""))
            print(f"  Final URL: {result['data']['final_url']}")
            print(f"  Status Code: {result['data']['status_code']}")
            print(f"  Elapsed Time: {result['data']['elapsed_seconds']:.2f}s")
            print(f"  Content Length: {result['data'].get('html_length', 0)} chars")
            if 'markdown_length' in result['data']:
                print(f"  Markdown Length: {result['data']['markdown_length']} chars")
            print()
            print("  Content Analysis:")
            print(f"    - Has internship keywords: {result['analysis']['has_internship_keywords']}")
            print(f"    - Has application keywords: {result['analysis']['has_application_keywords']}")
            print(f"    - Has structured data: {result['analysis']['has_structured_data']}")
            print(f"    - Potential listings: {result['analysis']['potential_listing_count']}")
            print()
            
            if result['data'].get('markdown_preview'):
                print("  Markdown Preview:")
                print("  " + "-" * 76)
                for line in result['data']['markdown_preview'].split('\n')[:20]:
                    print(f"  {line[:76]}")
                print("  " + "-" * 76)
                print()
    
    # Overall assessment
    print("=" * 80)
    print("OVERALL ASSESSMENT")
    print("=" * 80)
    print()
    
    successful_clients = [r for r in results if r['success']]
    
    if not successful_clients:
        print("❌ SITE NOT SCRAPABLE")
        print("   None of the scraping clients were able to access the site.")
        print()
        print("Reasons:")
        for result in results:
            print(f"  - {result['client']}: {result['error']}")
    else:
        print("✓ SITE IS SCRAPABLE")
        print(f"  Successfully scraped with {len(successful_clients)}/{len(results)} clients")
        print()
        
        # Check if any client found opportunity content
        has_opportunities = any(
            r['analysis'].get('has_internship_keywords') or r['analysis'].get('has_application_keywords')
            for r in successful_clients
        )
        
        if has_opportunities:
            print("✓ OPPORTUNITY CONTENT DETECTED")
            print("  The site contains internship/opportunity related keywords.")
        else:
            print("⚠ NO CLEAR OPPORTUNITY CONTENT")
            print("  The site may not have structured opportunity listings.")
        print()
        
        # Technical challenges
        print("Technical Considerations:")
        for result in successful_clients:
            if result['data']['status_code'] != 200:
                print(f"  ⚠ Non-200 status code: {result['data']['status_code']}")
            if not result['analysis'].get('has_structured_data'):
                print(f"  ⚠ No structured data detected (may require custom parsing)")
        print()
        
        # Recommendation
        print("Recommendation:")
        if has_opportunities and any(r['analysis'].get('has_structured_data') for r in successful_clients):
            print("  ✓ GOOD CANDIDATE for scraper addition")
            print("    - Site is accessible")
            print("    - Contains opportunity content")
            print("    - Has structured data")
        elif has_opportunities:
            print("  ⚠ MODERATE CANDIDATE for scraper addition")
            print("    - Site is accessible")
            print("    - Contains opportunity content")
            print("    - May require custom HTML parsing logic")
        else:
            print("  ✗ NOT RECOMMENDED for scraper addition")
            print("    - Site may not contain structured opportunity listings")
    
    print()
    print("=" * 80)
    
    # Save detailed results to JSON
    output_file = Path(__file__).parent / "tensorhack_scraping_test_results.json"
    with open(output_file, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print(f"Detailed results saved to: {output_file}")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())

# Made with Bob
