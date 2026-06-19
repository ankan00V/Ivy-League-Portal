from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from beanie import init_beanie
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import DuplicateKeyError

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import settings  # noqa: E402
from app.core.time import utc_now  # noqa: E402
from app.models.source_discovery import CompanySeed  # noqa: E402

TRACKING_QUERY_KEYS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "gclid",
    "fbclid",
    "msclkid",
}


def _clean_url(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlparse(str(value).strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return str(value).strip()
    query = urlencode(
        [(key, val) for key, val in parse_qsl(parsed.query, keep_blank_values=True) if key.lower() not in TRACKING_QUERY_KEYS],
        doseq=True,
    )
    return urlunparse((parsed.scheme, parsed.netloc.lower(), parsed.path or "/", "", query, ""))


def _seed(
    company_name: str,
    domain: str,
    industry: str,
    company_size: str,
    *,
    careers_url: str | None = None,
    india_presence: bool = True,
    student_friendly: bool = True,
    priority_tier: str | None = None,
    source_category: str | None = None,
    check_cadence_hours: int = 168,
    target_roles: list[str] | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    return {
        "company_name": company_name,
        "domain": domain,
        "careers_url": _clean_url(careers_url),
        "industry": industry,
        "company_size": company_size,
        "india_presence": india_presence,
        "student_friendly": student_friendly,
        "priority_tier": priority_tier,
        "source_category": source_category,
        "check_cadence_hours": check_cadence_hours,
        "target_roles": target_roles or ["internship", "0-1 years", "early career"],
        "notes": notes,
        "added_by": "bootstrap",
    }


def _official(
    company_name: str,
    domain: str,
    industry: str,
    source_category: str,
    careers_url: str,
    *,
    company_size: str = "enterprise",
    priority_tier: str = "tier_1",
    cadence_hours: int = 24,
    india_presence: bool = True,
) -> dict[str, Any]:
    return _seed(
        company_name,
        domain,
        industry,
        company_size,
        careers_url=careers_url,
        india_presence=india_presence,
        student_friendly=True,
        priority_tier=priority_tier,
        source_category=source_category,
        check_cadence_hours=cadence_hours,
        target_roles=["internship", "0-1 years", "student programs", "new grad", "graduate"],
        notes="Curated official internship watchlist; ingest only internships and 0-1 year early-career roles.",
    )


OFFICIAL_INTERNSHIP_WATCHLIST: list[dict[str, Any]] = [
    _official("Google", "google.com", "technology", "global_tech", "https://careers.google.com/"),
    _official("Microsoft", "microsoft.com", "technology", "global_tech", "https://careers.microsoft.com/"),
    _official("Amazon", "amazon.jobs", "technology", "global_tech", "https://www.amazon.jobs/"),
    _official("Meta", "metacareers.com", "technology", "global_tech", "https://www.metacareers.com/"),
    _official("Apple", "apple.com", "technology", "global_tech", "https://jobs.apple.com/"),
    _official("NVIDIA", "nvidia.com", "ai", "global_tech", "https://www.nvidia.com/en-in/about-nvidia/careers/"),
    _official("Adobe", "adobe.com", "technology", "global_tech", "https://careers.adobe.com/"),
    _official("Salesforce", "salesforce.com", "saas", "global_tech", "https://careers.salesforce.com/"),
    _official("Uber", "uber.com", "mobility", "global_tech", "https://www.uber.com/us/en/careers/"),
    _official("Atlassian", "atlassian.com", "saas", "global_tech", "https://www.atlassian.com/company/careers"),
    _official("Tower Research Capital", "tower-research.com", "quant trading", "quant_trading", "https://www.tower-research.com/open-positions/"),
    _official("Jane Street", "janestreet.com", "quant trading", "quant_trading", "https://www.janestreet.com/join-jane-street/"),
    _official("Hudson River Trading", "hudsonrivertrading.com", "quant trading", "quant_trading", "https://www.hudsonrivertrading.com/careers/"),
    _official("Optiver", "optiver.com", "quant trading", "quant_trading", "https://optiver.com/working-at-optiver/"),
    _official("IMC Trading", "imc.com", "quant trading", "quant_trading", "https://www.imc.com/us/careers/"),
    _official("Flipkart", "flipkartcareers.com", "technology", "indian_product", "https://www.flipkartcareers.com/"),
    _official("Meesho", "meesho.io", "commerce", "indian_product", "https://www.meesho.io/jobs"),
    _official("PhonePe", "phonepe.com", "fintech", "indian_product", "https://www.phonepe.com/careers/"),
    _official("Razorpay", "razorpay.com", "fintech", "indian_product", "https://razorpay.com/jobs/"),
    _official("CRED", "cred.club", "fintech", "indian_product", "https://careers.cred.club/"),
    _official("Swiggy", "swiggy.com", "consumer internet", "indian_product", "https://careers.swiggy.com/"),
    _official("Zomato", "zomato.com", "consumer internet", "indian_product", "https://www.zomato.com/careers"),
    _official("Groww", "groww.in", "fintech", "indian_product", "https://groww.in/careers"),
    _official("Zerodha", "zerodha.com", "fintech", "indian_product", "https://careers.zerodha.com/"),
    _official("Freshworks", "freshworks.com", "saas", "indian_product", "https://www.freshworks.com/company/careers/"),
    _official("TCS", "tcs.com", "it services", "indian_it", "https://www.tcs.com/careers"),
    _official("Infosys", "infosys.com", "it services", "indian_it", "https://www.infosys.com/careers.html"),
    _official("Wipro", "wipro.com", "it services", "indian_it", "https://careers.wipro.com/"),
    _official("HCLTech", "hcltech.com", "it services", "indian_it", "https://www.hcltech.com/careers"),
    _official("Tech Mahindra", "techmahindra.com", "it services", "indian_it", "https://careers.techmahindra.com/"),
    _official("Accenture", "accenture.com", "consulting", "indian_it", "https://www.accenture.com/in-en/careers"),
    _official("Capgemini", "capgemini.com", "consulting", "indian_it", "https://www.capgemini.com/careers/"),
    _official("Cognizant", "cognizant.com", "it services", "indian_it", "https://careers.cognizant.com/"),
    _official("IBM", "ibm.com", "enterprise software", "indian_it", "https://www.ibm.com/careers"),
    _official("Oracle", "oracle.com", "enterprise software", "indian_it", "https://careers.oracle.com/"),
    _official("ISRO", "isro.gov.in", "research", "government_psu", "https://www.isro.gov.in/Careers.html"),
    _official("DRDO", "drdo.gov.in", "research", "government_psu", "https://www.drdo.gov.in/careers"),
    _official("BARC", "barc.gov.in", "research", "government_psu", "https://www.barc.gov.in/careers/"),
    _official("BEL", "bel-india.in", "defence electronics", "government_psu", "https://bel-india.in/careers/"),
    _official("BHEL", "bhel.com", "engineering", "government_psu", "https://www.bhel.com/careers"),
    _official("HAL", "hal-india.co.in", "aerospace", "government_psu", "https://hal-india.co.in/careers"),
    _official("NTPC", "ntpc.co.in", "energy", "government_psu", "https://careers.ntpc.co.in/"),
    _official("ONGC", "ongcindia.com", "energy", "government_psu", "https://ongcindia.com/web/eng/career"),
    _official("GAIL", "gailonline.com", "energy", "government_psu", "https://gailonline.com/CR-careers.html"),
    _official("SAIL", "sail.co.in", "manufacturing", "government_psu", "https://www.sail.co.in/en/careers"),
    _official("NALCO", "nalcoindia.com", "manufacturing", "government_psu", "https://nalcoindia.com/career/"),
    _official("Power Grid Corporation of India", "powergrid.in", "energy", "government_psu", "https://www.powergrid.in/job-opportunities"),
    _official("Indian Oil Corporation", "iocl.com", "energy", "government_psu", "https://iocl.com/latest-job-opening"),
    _official("Coal India", "coalindia.in", "energy", "government_psu", "https://www.coalindia.in/career-cil/"),
    _official("NPCIL", "npcilcareers.co.in", "energy", "government_psu", "https://www.npcilcareers.co.in/"),
    _official("IIT Madras Research Park", "respark.iitm.ac.in", "research", "research_org", "https://respark.iitm.ac.in/careers"),
    _official("C-DAC", "cdac.in", "research", "research_org", "https://www.cdac.in/index.aspx?id=ca_acts_Careers"),
    _official("CSIR", "csir.res.in", "research", "research_org", "https://www.csir.res.in/career-opportunities"),
    _official("TIFR", "tifr.res.in", "research", "research_org", "https://www.tifr.res.in/positions"),
    _official("IISc Bangalore", "iisc.ac.in", "research", "research_org", "https://iisc.ac.in/careers/"),
    _official("McKinsey", "mckinsey.com", "consulting", "consulting_analytics", "https://www.mckinsey.com/careers"),
    _official("BCG", "bcg.com", "consulting", "consulting_analytics", "https://careers.bcg.com/"),
    _official("Bain", "bain.com", "consulting", "consulting_analytics", "https://www.bain.com/careers/"),
    _official("Goldman Sachs", "goldmansachs.com", "finance", "finance", "https://www.goldmansachs.com/careers/"),
    _official("JPMorgan Chase", "jpmorganchase.com", "finance", "finance", "https://careers.jpmorgan.com/"),
    _official("Morgan Stanley", "morganstanley.com", "finance", "finance", "https://www.morganstanley.com/careers"),
    _official("American Express", "americanexpress.com", "finance", "finance", "https://www.americanexpress.com/en-us/careers/"),
    _official("Deloitte", "deloitte.com", "consulting", "consulting_analytics", "https://www.deloitte.com/global/en/careers.html"),
    _official("EY", "ey.com", "consulting", "consulting_analytics", "https://www.ey.com/en_in/careers"),
    _official("PwC", "pwc.com", "consulting", "consulting_analytics", "https://www.pwc.com/gx/en/careers.html"),
    _official("KPMG", "kpmg.com", "consulting", "consulting_analytics", "https://kpmg.com/xx/en/home/careers.html"),
    _official("Mu Sigma", "mu-sigma.com", "analytics", "consulting_analytics", "https://www.mu-sigma.com/careers/"),
    _official("Tata Motors", "tatamotors.com", "automotive", "automotive_manufacturing", "https://careers.tatamotors.com/"),
    _official("Mahindra", "mahindra.com", "manufacturing", "automotive_manufacturing", "https://jobs.mahindracareers.com/"),
    _official("Maruti Suzuki", "marutisuzuki.com", "automotive", "automotive_manufacturing", "https://www.marutisuzuki.com/corporate/careers"),
    _official("Ashok Leyland", "ashokleyland.com", "automotive", "automotive_manufacturing", "https://www.ashokleyland.com/careers"),
    _official("Mercedes-Benz", "mercedes-benz.com", "automotive", "automotive_manufacturing", "https://group.mercedes-benz.com/careers/"),
    _official("Bosch India", "bosch.in", "automotive", "automotive_manufacturing", "https://www.bosch.in/careers/"),
    _official("Siemens", "siemens.com", "engineering", "automotive_manufacturing", "https://www.siemens.com/global/en/company/jobs.html"),
    _official("Schneider Electric", "se.com", "engineering", "automotive_manufacturing", "https://www.se.com/ww/en/about-us/careers/overview.jsp"),
    _official("Airbus", "airbus.com", "aerospace", "aerospace_aviation", "https://www.airbus.com/en/careers"),
    _official("Boeing", "boeing.com", "aerospace", "aerospace_aviation", "https://jobs.boeing.com/"),
    _official("Rolls-Royce", "rolls-royce.com", "aerospace", "aerospace_aviation", "https://careers.rolls-royce.com/"),
    _official("GE Aerospace", "gecareers.com", "aerospace", "aerospace_aviation", "https://jobs.gecareers.com/"),
    _official("Reliance Industries", "ril.com", "energy", "energy_infrastructure", "https://careers.ril.com/"),
    _official("Adani Group", "adani.com", "infrastructure", "energy_infrastructure", "https://careers.adani.com/"),
    _official("Larsen & Toubro", "larsentoubro.com", "engineering", "energy_infrastructure", "https://careers.larsentoubro.com/"),
    _official("Fractal Analytics", "fractal.ai", "analytics", "analytics_data_science", "https://fractal.ai/careers/"),
    _official("Tiger Analytics", "tigeranalytics.com", "analytics", "analytics_data_science", "https://www.tigeranalytics.com/careers/"),
    _official("EXL", "exlservice.com", "analytics", "analytics_data_science", "https://www.exlservice.com/careers"),
    _official("ZS", "zs.com", "consulting analytics", "analytics_data_science", "https://www.zs.com/careers"),
    _official("HSBC", "hsbc.com", "finance", "banking_financial_services", "https://www.hsbc.com/careers"),
    _official("Citi", "citi.com", "finance", "banking_financial_services", "https://jobs.citi.com/"),
    _official("Deutsche Bank", "db.com", "finance", "banking_financial_services", "https://careers.db.com/"),
    _official("Wells Fargo", "wellsfargo.com", "finance", "banking_financial_services", "https://www.wellsfargojobs.com/"),
    _official("Mastercard", "mastercard.com", "fintech", "banking_financial_services", "https://careers.mastercard.com/"),
    _official("Visa", "visa.com", "fintech", "banking_financial_services", "https://corporate.visa.com/en/careers.html"),
    _official("Hindustan Unilever", "unilever.com", "consumer goods", "fmcg", "https://careers.unilever.com/"),
    _official("Procter & Gamble", "pgcareers.com", "consumer goods", "fmcg", "https://www.pgcareers.com/"),
    _official("Nestle", "nestle.com", "consumer goods", "fmcg", "https://www.nestle.com/jobs"),
    _official("ITC", "itcportal.com", "consumer goods", "fmcg", "https://www.itcportal.com/careers/"),
    _official("Coca-Cola", "coca-colacompany.com", "consumer goods", "fmcg", "https://www.coca-colacompany.com/careers"),
    _official("PepsiCo", "pepsicojobs.com", "consumer goods", "fmcg", "https://www.pepsicojobs.com/"),
    _official("Juspay", "juspay.in", "fintech", "hidden_gems", "https://juspay.in/careers"),
    _official("Zoho", "zoho.com", "saas", "hidden_gems", "https://www.zoho.com/careers/"),
    _official("Postman", "postman.com", "saas", "hidden_gems", "https://www.postman.com/company/careers/"),
    _official("BrowserStack", "browserstack.com", "saas", "hidden_gems", "https://www.browserstack.com/careers"),
    _official("ShareChat", "sharechat.com", "consumer internet", "hidden_gems", "https://sharechat.com/careers"),
    _official("Unacademy", "unacademy.com", "edtech", "hidden_gems", "https://careers.unacademy.com/"),
    _official("Navi", "navi.com", "fintech", "hidden_gems", "https://navi.com/careers"),
]


RAW_SEEDS: list[dict[str, Any]] = [
    _seed("Flipkart", "flipkartcareers.com", "technology", "enterprise", careers_url="https://www.flipkartcareers.com/"),
    _seed("Swiggy", "swiggy.com", "consumer internet", "enterprise", careers_url="https://careers.swiggy.com/"),
    _seed("Zomato", "zomato.com", "consumer internet", "enterprise", careers_url="https://www.zomato.com/careers"),
    _seed("Razorpay", "razorpay.com", "fintech", "enterprise", careers_url="https://razorpay.com/jobs/"),
    _seed("CRED", "cred.club", "fintech", "mid", careers_url="https://careers.cred.club/"),
    _seed("PhonePe", "phonepe.com", "fintech", "enterprise", careers_url="https://www.phonepe.com/careers/"),
    _seed("Meesho", "meesho.io", "commerce", "enterprise", careers_url="https://www.meesho.io/jobs"),
    _seed("Zepto", "zeptonow.com", "commerce", "mid", careers_url="https://www.zeptonow.com/careers"),
    _seed("Ola", "olaelectric.com", "mobility", "enterprise", careers_url="https://olaelectric.com/careers"),
    _seed("Myntra", "myntra.com", "commerce", "enterprise", careers_url="https://careers.myntra.com/"),
    _seed("Nykaa", "nykaa.com", "commerce", "enterprise", careers_url="https://www.nykaa.com/careers"),
    _seed("PolicyBazaar", "policybazaar.com", "fintech", "enterprise", careers_url="https://www.policybazaar.com/careers/"),
    _seed("Paytm", "paytm.com", "fintech", "enterprise", careers_url="https://paytm.com/careers/"),
    _seed("InMobi", "inmobi.com", "adtech", "enterprise", careers_url="https://www.inmobi.com/company/careers/"),
    _seed("Freshworks", "freshworks.com", "saas", "enterprise", careers_url="https://www.freshworks.com/company/careers/"),
    _seed("Zoho", "zoho.com", "saas", "enterprise", careers_url="https://www.zoho.com/careers/"),
    _seed("Infosys", "infosys.com", "it services", "enterprise", careers_url="https://www.infosys.com/careers/"),
    _seed("TCS", "tcs.com", "it services", "enterprise", careers_url="https://www.tcs.com/careers"),
    _seed("Wipro", "wipro.com", "it services", "enterprise", careers_url="https://careers.wipro.com/"),
    _seed("HCLTech", "hcltech.com", "it services", "enterprise", careers_url="https://www.hcltech.com/careers"),
    _seed("Tech Mahindra", "techmahindra.com", "it services", "enterprise", careers_url="https://www.techmahindra.com/en-in/careers/"),
    _seed("Persistent", "persistent.com", "it services", "enterprise", careers_url="https://www.persistent.com/careers/"),
    _seed("Mphasis", "mphasis.com", "it services", "enterprise", careers_url="https://www.mphasis.com/home/careers.html"),
    _seed("NIIT", "niit.com", "edtech", "enterprise", careers_url="https://www.niit.com/india/careers"),
    _seed("BYJU'S", "byjus.com", "edtech", "enterprise", careers_url="https://byjus.com/careers/"),
    _seed("Unacademy", "unacademy.com", "edtech", "enterprise", careers_url="https://unacademy.com/careers"),
    _seed("Vedantu", "vedantu.com", "edtech", "mid", careers_url="https://www.vedantu.com/careers"),
    _seed("Simplilearn", "simplilearn.com", "edtech", "mid", careers_url="https://www.simplilearn.com/careers"),
    _seed("upGrad", "upgrad.com", "edtech", "enterprise", careers_url="https://www.upgrad.com/careers/"),
    _seed("Scaler", "scaler.com", "edtech", "mid", careers_url="https://www.scaler.com/careers/"),
    _seed("Dream11", "dream11.com", "gaming", "enterprise", careers_url="https://www.dream11.com/careers"),
    _seed("MPL", "mpl.live", "gaming", "mid", careers_url="https://www.mpl.live/careers"),
    _seed("Gameskraft", "gameskraft.com", "gaming", "mid", careers_url="https://www.gameskraft.com/careers/"),
    _seed("BrowserStack", "browserstack.com", "saas", "enterprise", careers_url="https://www.browserstack.com/careers"),
    _seed("Postman", "postman.com", "saas", "enterprise", careers_url="https://www.postman.com/company/careers/"),
    _seed("Chargebee", "chargebee.com", "saas", "enterprise", careers_url="https://www.chargebee.com/careers/"),
    _seed("Whatfix", "whatfix.com", "saas", "mid", careers_url="https://whatfix.com/careers/"),
    _seed("Icertis", "icertis.com", "saas", "enterprise", careers_url="https://www.icertis.com/careers/"),
    _seed("Darwinbox", "darwinbox.com", "saas", "mid", careers_url="https://darwinbox.com/careers/"),
    _seed("Hasura", "hasura.io", "developer tools", "mid", careers_url="https://hasura.io/careers/"),
    _seed("Zeta", "zeta.tech", "fintech", "enterprise", careers_url="https://www.zeta.tech/careers"),
    _seed("Pine Labs", "pinelabs.com", "fintech", "enterprise", careers_url="https://www.pinelabs.com/careers"),
    _seed("Juspay", "juspay.in", "fintech", "mid", careers_url="https://juspay.in/careers"),
    _seed("Groww", "groww.in", "fintech", "enterprise", careers_url="https://groww.in/careers"),
    _seed("Zerodha", "zerodha.com", "fintech", "mid", careers_url="https://zerodha.com/careers/"),
    _seed("Upstox", "upstox.com", "fintech", "mid", careers_url="https://upstox.com/careers/"),
    _seed("CoinDCX", "coindcx.com", "fintech", "mid", careers_url="https://coindcx.com/careers"),
    _seed("CoinSwitch", "coinswitch.co", "fintech", "mid", careers_url="https://coinswitch.co/careers"),
    _seed("ClearTax", "cleartax.in", "fintech", "mid", careers_url="https://cleartax.in/careers"),
    _seed("Khatabook", "khatabook.com", "fintech", "mid", careers_url="https://khatabook.com/careers"),
    _seed("Google", "google.com", "technology", "enterprise", careers_url="https://careers.google.com/"),
    _seed("Microsoft", "microsoft.com", "technology", "enterprise", careers_url="https://careers.microsoft.com/"),
    _seed("Amazon", "amazon.jobs", "technology", "enterprise", careers_url="https://www.amazon.jobs/en/"),
    _seed("Meta", "metacareers.com", "technology", "enterprise", careers_url="https://www.metacareers.com/"),
    _seed("Apple", "apple.com", "technology", "enterprise", careers_url="https://jobs.apple.com/"),
    _seed("Cisco", "cisco.com", "networking", "enterprise", careers_url="https://jobs.cisco.com/"),
    _seed("ServiceNow", "servicenow.com", "saas", "enterprise", careers_url="https://careers.servicenow.com/"),
    _seed("NVIDIA", "nvidia.com", "ai", "enterprise", careers_url="https://www.nvidia.com/en-us/about-nvidia/careers/"),
    _seed("Adobe", "adobe.com", "technology", "enterprise", careers_url="https://careers.adobe.com/"),
    _seed("Salesforce", "salesforce.com", "saas", "enterprise", careers_url="https://www.salesforce.com/company/careers/"),
    _seed("SAP", "sap.com", "enterprise software", "enterprise", careers_url="https://jobs.sap.com/"),
    _seed("Oracle", "oracle.com", "enterprise software", "enterprise", careers_url="https://www.oracle.com/careers/"),
    _seed("IBM", "ibm.com", "enterprise software", "enterprise", careers_url="https://www.ibm.com/careers"),
    _seed("Accenture", "accenture.com", "consulting", "enterprise", careers_url="https://www.accenture.com/in-en/careers"),
    _seed("Capgemini", "capgemini.com", "consulting", "enterprise", careers_url="https://www.capgemini.com/careers/"),
    _seed("Deloitte", "deloitte.com", "consulting", "enterprise", careers_url="https://www.deloitte.com/global/en/careers.html"),
    _seed("EY", "ey.com", "consulting", "enterprise", careers_url="https://www.ey.com/en_in/careers"),
    _seed("PwC", "pwc.in", "consulting", "enterprise", careers_url="https://www.pwc.in/careers.html"),
    _seed("KPMG", "kpmg.com", "consulting", "enterprise", careers_url="https://kpmg.com/xx/en/home/careers.html"),
    _seed("McKinsey", "mckinsey.com", "consulting", "enterprise", careers_url="https://www.mckinsey.com/careers"),
    _seed("BCG", "bcg.com", "consulting", "enterprise", careers_url="https://careers.bcg.com/"),
    _seed("Bain", "bain.com", "consulting", "enterprise", careers_url="https://www.bain.com/careers/"),
    _seed("Goldman Sachs", "goldmansachs.com", "finance", "enterprise", careers_url="https://www.goldmansachs.com/careers/"),
    _seed("Morgan Stanley", "morganstanley.com", "finance", "enterprise", careers_url="https://www.morganstanley.com/careers"),
    _seed("JPMorgan Chase", "jpmorganchase.com", "finance", "enterprise", careers_url="https://careers.jpmorgan.com/"),
    _seed("Citibank", "citi.com", "finance", "enterprise", careers_url="https://jobs.citi.com/"),
    _seed("HSBC", "hsbc.com", "finance", "enterprise", careers_url="https://www.hsbc.com/careers"),
    _seed("American Express", "americanexpress.com", "finance", "enterprise", careers_url="https://www.americanexpress.com/en-us/careers/"),
    _seed("Visa", "visa.com", "fintech", "enterprise", careers_url="https://usa.visa.com/careers.html"),
    _seed("Mastercard", "mastercard.com", "fintech", "enterprise", careers_url="https://www.mastercard.com/global/en/vision/who-we-are/careers.html"),
    _seed("Uber", "uber.com", "mobility", "enterprise", careers_url="https://www.uber.com/us/en/careers/"),
    _seed("Airbnb", "airbnb.com", "marketplace", "enterprise", careers_url="https://careers.airbnb.com/"),
    _seed("LinkedIn", "linkedin.com", "technology", "enterprise", careers_url="https://careers.linkedin.com/"),
    _seed("Lenskart", "lenskart.com", "commerce", "enterprise", careers_url="https://www.lenskart.com/careers"),
    _seed("Mamaearth", "mamaearth.in", "consumer goods", "mid", careers_url="https://mamaearth.in/careers"),
    _seed("HealthKart", "healthkart.com", "healthcare", "mid", careers_url="https://www.healthkart.com/careers"),
    _seed("Tata 1mg", "1mg.com", "healthcare", "enterprise", careers_url="https://www.1mg.com/jobs"),
    _seed("PharmEasy", "pharmeasy.in", "healthcare", "enterprise", careers_url="https://pharmeasy.in/careers"),
    _seed("Practo", "practo.com", "healthcare", "mid", careers_url="https://www.practo.com/company/careers"),
    _seed("Urban Company", "urbancompany.com", "marketplace", "enterprise", careers_url="https://www.urbancompany.com/careers"),
    _seed("Dunzo", "dunzo.com", "logistics", "mid", careers_url="https://www.dunzo.com/careers"),
    _seed("Porter", "porter.in", "logistics", "mid", careers_url="https://porter.in/careers"),
    _seed("Delhivery", "delhivery.com", "logistics", "enterprise", careers_url="https://www.delhivery.com/careers"),
    _seed("Shiprocket", "shiprocket.in", "logistics", "mid", careers_url="https://www.shiprocket.in/careers/"),
    _seed("BlackBuck", "blackbuck.com", "logistics", "mid", careers_url="https://blackbuck.com/careers/"),
    _seed("ElasticRun", "elastic.run", "logistics", "mid", careers_url="https://elastic.run/careers/"),
    _seed("NoBroker", "nobroker.in", "proptech", "mid", careers_url="https://www.nobroker.in/careers"),
    _seed("Housing.com", "housing.com", "proptech", "enterprise", careers_url="https://housing.com/careers"),
    _seed("Livspace", "livspace.com", "design", "enterprise", careers_url="https://www.livspace.com/in/careers"),
    _seed("Wakefit", "wakefit.co", "commerce", "mid", careers_url="https://www.wakefit.co/careers"),
    _seed("CarDekho", "cardekho.com", "automotive", "enterprise", careers_url="https://www.cardekho.com/careers"),
    _seed("Spinny", "spinny.com", "automotive", "mid", careers_url="https://www.spinny.com/careers/"),
    _seed("Cars24", "cars24.com", "automotive", "enterprise", careers_url="https://www.cars24.com/careers/"),
    _seed("IISc", "iisc.ac.in", "research", "enterprise", careers_url="https://iisc.ac.in/careers/"),
    _seed("IIT Bombay", "iitb.ac.in", "research", "enterprise", careers_url="https://www.iitb.ac.in/en/careers"),
    _seed("IIT Delhi", "iitd.ac.in", "research", "enterprise", careers_url="https://home.iitd.ac.in/jobs.php"),
    _seed("IIT Madras", "iitm.ac.in", "research", "enterprise", careers_url="https://www.iitm.ac.in/careers"),
    _seed("IIT Kanpur", "iitk.ac.in", "research", "enterprise", careers_url="https://www.iitk.ac.in/new/recruitment"),
    _seed("IIT Kharagpur", "iitkgp.ac.in", "research", "enterprise", careers_url="https://www.iitkgp.ac.in/career"),
    _seed("IIT Roorkee", "iitr.ac.in", "research", "enterprise", careers_url="https://iitr.ac.in/Careers/"),
    _seed("IIT Guwahati", "iitg.ac.in", "research", "enterprise", careers_url="https://www.iitg.ac.in/recruitment/"),
    _seed("ISRO", "isro.gov.in", "research", "enterprise", careers_url="https://www.isro.gov.in/Careers.html"),
    _seed("DRDO", "drdo.gov.in", "research", "enterprise", careers_url="https://www.drdo.gov.in/careers"),
    _seed("TIFR", "tifr.res.in", "research", "enterprise", careers_url="https://www.tifr.res.in/positions"),
    _seed("C-DAC", "cdac.in", "research", "enterprise", careers_url="https://www.cdac.in/index.aspx?id=ca_acts_Careers"),
    _seed("NAL", "nal.res.in", "research", "enterprise", careers_url="https://www.nal.res.in/en/careers"),
    _seed("BARC", "barc.gov.in", "research", "enterprise", careers_url="https://www.barc.gov.in/careers/"),
    _seed("CSIR", "csir.res.in", "research", "enterprise", careers_url="https://www.csir.res.in/career-opportunities"),
    _seed("NITI Aayog", "niti.gov.in", "public policy", "enterprise", careers_url="https://www.niti.gov.in/career"),
    _seed("RBI", "rbi.org.in", "finance", "enterprise", careers_url="https://opportunities.rbi.org.in/"),
    _seed("SEBI", "sebi.gov.in", "finance", "enterprise", careers_url="https://www.sebi.gov.in/sebiweb/other/careerdetail.jsp"),
    _seed("NASSCOM", "nasscom.in", "industry body", "enterprise", careers_url="https://nasscom.in/careers"),
    _seed("Digital India", "digitalindia.gov.in", "public technology", "enterprise", careers_url="https://www.digitalindia.gov.in/careers/"),
    _seed("Stripe", "stripe.com", "fintech", "enterprise", careers_url="https://stripe.com/jobs"),
    _seed("Notion", "notion.so", "saas", "mid", careers_url="https://www.notion.so/careers"),
    _seed("Linear", "linear.app", "saas", "startup", careers_url="https://linear.app/careers"),
    _seed("Figma", "figma.com", "design", "enterprise", careers_url="https://www.figma.com/careers/"),
    _seed("Atlassian", "atlassian.com", "saas", "enterprise", careers_url="https://www.atlassian.com/company/careers"),
    _seed("Canva", "canva.com", "design", "enterprise", careers_url="https://www.canva.com/careers/"),
    _seed("GitLab", "gitlab.com", "developer tools", "enterprise", careers_url="https://about.gitlab.com/jobs/"),
    _seed("Automattic", "automattic.com", "developer tools", "enterprise", careers_url="https://automattic.com/work-with-us/"),
    _seed("Zapier", "zapier.com", "saas", "mid", careers_url="https://zapier.com/jobs"),
    _seed("Remote", "remote.com", "hrtech", "mid", careers_url="https://remote.com/careers"),
    _seed("Toptal", "toptal.com", "talent marketplace", "mid", careers_url="https://www.toptal.com/careers"),
    _seed("Deel", "deel.com", "hrtech", "enterprise", careers_url="https://www.deel.com/careers/"),
    _seed("Shopify", "shopify.com", "commerce", "enterprise", careers_url="https://www.shopify.com/careers"),
    _seed("Cloudflare", "cloudflare.com", "cloud", "enterprise", careers_url="https://www.cloudflare.com/careers/"),
    _seed("Datadog", "datadoghq.com", "cloud", "enterprise", careers_url="https://www.datadoghq.com/careers/"),
    _seed("Snowflake", "snowflake.com", "data", "enterprise", careers_url="https://careers.snowflake.com/"),
    _seed("Databricks", "databricks.com", "data", "enterprise", careers_url="https://www.databricks.com/company/careers"),
    _seed("MongoDB", "mongodb.com", "data", "enterprise", careers_url="https://www.mongodb.com/careers"),
    _seed("Confluent", "confluent.io", "data", "enterprise", careers_url="https://www.confluent.io/careers/"),
    _seed("Hugging Face", "huggingface.co", "ai", "mid", careers_url="https://huggingface.co/join"),
    _seed("MakeMyTrip", "makemytrip.com", "travel", "enterprise", careers_url="https://careers.makemytrip.com/"),
    _seed("Ixigo", "ixigo.com", "travel", "mid", careers_url="https://www.ixigo.com/about/careers"),
    _seed("EaseMyTrip", "easemytrip.com", "travel", "enterprise", careers_url="https://www.easemytrip.com/careers.html"),
    _seed("OYO", "oyorooms.com", "travel", "enterprise", careers_url="https://www.oyorooms.com/careers/"),
    _seed("Tata Digital", "tatadigital.com", "commerce", "enterprise", careers_url="https://www.tatadigital.com/careers"),
    _seed("Reliance Jio", "jio.com", "telecom", "enterprise", careers_url="https://careers.jio.com/"),
    _seed("Airtel", "airtel.in", "telecom", "enterprise", careers_url="https://www.airtel.in/careers/"),
    _seed("Vodafone Idea", "myvi.in", "telecom", "enterprise", careers_url="https://www.myvi.in/careers"),
    _seed("Tata Steel", "tatasteel.com", "manufacturing", "enterprise", careers_url="https://www.tatasteel.com/careers/"),
    _seed("Mahindra", "mahindra.com", "manufacturing", "enterprise", careers_url="https://www.mahindra.com/careers"),
    _seed("Tata Motors", "tatamotors.com", "automotive", "enterprise", careers_url="https://www.tatamotors.com/careers/"),
    _seed("Maruti Suzuki", "marutisuzuki.com", "automotive", "enterprise", careers_url="https://www.marutisuzuki.com/corporate/careers"),
    _seed("Hero MotoCorp", "heromotocorp.com", "automotive", "enterprise", careers_url="https://www.heromotocorp.com/en-in/careers/"),
    _seed("Bajaj Auto", "bajajauto.com", "automotive", "enterprise", careers_url="https://www.bajajauto.com/careers"),
    _seed("Larsen & Toubro", "larsentoubro.com", "engineering", "enterprise", careers_url="https://www.larsentoubro.com/corporate/careers/"),
    _seed("Adani Group", "adani.com", "infrastructure", "enterprise", careers_url="https://www.adani.com/careers"),
    _seed("JSW", "jsw.in", "manufacturing", "enterprise", careers_url="https://www.jsw.in/careers"),
    _seed("Asian Paints", "asianpaints.com", "consumer goods", "enterprise", careers_url="https://www.asianpaints.com/careers.html"),
    _seed("Hindustan Unilever", "hul.co.in", "consumer goods", "enterprise", careers_url="https://www.hul.co.in/careers/"),
    _seed("ITC", "itcportal.com", "consumer goods", "enterprise", careers_url="https://www.itcportal.com/careers/"),
    _seed("Nestle India", "nestle.in", "consumer goods", "enterprise", careers_url="https://www.nestle.in/jobs"),
    _seed("L'Oreal India", "loreal.com", "consumer goods", "enterprise", careers_url="https://careers.loreal.com/"),
    _seed("Dr. Reddy's", "drreddys.com", "healthcare", "enterprise", careers_url="https://careers.drreddys.com/"),
    _seed("Sun Pharma", "sunpharma.com", "healthcare", "enterprise", careers_url="https://sunpharma.com/careers/"),
    _seed("Cipla", "cipla.com", "healthcare", "enterprise", careers_url="https://www.cipla.com/careers"),
    _seed("Biocon", "biocon.com", "healthcare", "enterprise", careers_url="https://www.biocon.com/careers/"),
    _seed("Apollo Hospitals", "apollohospitals.com", "healthcare", "enterprise", careers_url="https://www.apollohospitals.com/careers/"),
    _seed("Fortis Healthcare", "fortishealthcare.com", "healthcare", "enterprise", careers_url="https://www.fortishealthcare.com/careers"),
    _seed("Max Healthcare", "maxhealthcare.in", "healthcare", "enterprise", careers_url="https://www.maxhealthcare.in/careers"),
    _seed("Manipal Hospitals", "manipalhospitals.com", "healthcare", "enterprise", careers_url="https://www.manipalhospitals.com/careers/"),
    _seed("HDFC Bank", "hdfcbank.com", "finance", "enterprise", careers_url="https://www.hdfcbank.com/personal/about-us/careers"),
    _seed("ICICI Bank", "icicibank.com", "finance", "enterprise", careers_url="https://www.icicibank.com/about-us/career"),
    _seed("Axis Bank", "axisbank.com", "finance", "enterprise", careers_url="https://www.axisbank.com/careers"),
    _seed("Kotak Mahindra Bank", "kotak.com", "finance", "enterprise", careers_url="https://www.kotak.com/en/about-us/careers.html"),
    _seed("SBI", "sbi.co.in", "finance", "enterprise", careers_url="https://sbi.co.in/web/careers"),
    _seed("Bank of Baroda", "bankofbaroda.in", "finance", "enterprise", careers_url="https://www.bankofbaroda.in/career"),
    _seed("HDFC Life", "hdfclife.com", "insurance", "enterprise", careers_url="https://www.hdfclife.com/about-us/careers"),
    _seed("ICICI Prudential", "iciciprulife.com", "insurance", "enterprise", careers_url="https://www.iciciprulife.com/about-us/careers.html"),
    _seed("Acko", "acko.com", "insurance", "mid", careers_url="https://www.acko.com/careers/"),
    _seed("Digit Insurance", "godigit.com", "insurance", "mid", careers_url="https://www.godigit.com/careers"),
    _seed("Mu Sigma", "mu-sigma.com", "analytics", "enterprise", careers_url="https://www.mu-sigma.com/careers/"),
    _seed("Fractal Analytics", "fractal.ai", "analytics", "enterprise", careers_url="https://fractal.ai/careers/"),
    _seed("Tiger Analytics", "tigeranalytics.com", "analytics", "enterprise", careers_url="https://www.tigeranalytics.com/careers/"),
    _seed("LatentView", "latentview.com", "analytics", "enterprise", careers_url="https://www.latentview.com/careers/"),
    _seed("Quantiphi", "quantiphi.com", "ai", "enterprise", careers_url="https://quantiphi.com/careers/"),
    _seed("Mad Street Den", "madstreetden.com", "ai", "mid", careers_url="https://www.madstreetden.com/careers"),
    _seed("Niramai", "niramai.com", "ai healthcare", "startup", careers_url="https://www.niramai.com/careers/"),
    _seed("SigTuple", "sigtuple.com", "ai healthcare", "startup", careers_url="https://sigtuple.com/careers/"),
    _seed("GreyOrange", "greyorange.com", "robotics", "enterprise", careers_url="https://www.greyorange.com/careers/"),
    _seed("ideaForge", "ideaforgetech.com", "drones", "mid", careers_url="https://www.ideaforgetech.com/careers/"),
    _seed("Skyroot Aerospace", "skyroot.in", "aerospace", "startup", careers_url="https://skyroot.in/careers/"),
    _seed("Agnikul", "agnikul.in", "aerospace", "startup", careers_url="https://agnikul.in/careers/"),
    _seed("Pixxel", "pixxel.space", "aerospace", "startup", careers_url="https://www.pixxel.space/careers"),
    _seed("Log9 Materials", "log9materials.com", "climate tech", "startup", careers_url="https://www.log9materials.com/careers"),
    _seed("Ather Energy", "atherenergy.com", "mobility", "enterprise", careers_url="https://www.atherenergy.com/careers"),
    _seed("BluSmart", "blu-smart.com", "mobility", "mid", careers_url="https://blu-smart.com/careers"),
    _seed("Yulu", "yulu.bike", "mobility", "mid", careers_url="https://www.yulu.bike/careers"),
    _seed("Bounce", "bounceshare.com", "mobility", "mid", careers_url="https://bounceshare.com/careers"),
    _seed("Classplus", "classplusapp.com", "edtech", "mid", careers_url="https://classplusapp.com/careers"),
    _seed("Teachmint", "teachmint.com", "edtech", "mid", careers_url="https://www.teachmint.com/careers"),
    _seed("Cuemath", "cuemath.com", "edtech", "mid", careers_url="https://www.cuemath.com/careers/"),
    _seed("Toppr", "toppr.com", "edtech", "enterprise", careers_url="https://www.toppr.com/careers/"),
    _seed("Physics Wallah", "pw.live", "edtech", "enterprise", careers_url="https://www.pw.live/careers"),
    _seed("Vedantu Innovation", "vedantu.com", "edtech", "mid", careers_url="https://www.vedantu.com/careers"),
]


def initial_company_seeds() -> list[dict[str, Any]]:
    seen: set[str] = set()
    rows: list[dict[str, Any]] = []
    for item in [*OFFICIAL_INTERNSHIP_WATCHLIST, *RAW_SEEDS]:
        domain = str(item["domain"]).strip().lower().removeprefix("www.")
        if domain in seen:
            continue
        seen.add(domain)
        normalized = dict(item)
        normalized["domain"] = domain
        normalized["careers_url"] = _clean_url(normalized.get("careers_url"))
        rows.append(normalized)
    return rows


async def bootstrap_company_seeds() -> dict[str, int]:
    client = AsyncIOMotorClient(settings.MONGODB_URL)
    await init_beanie(database=client[settings.MONGODB_DB_NAME], document_models=[CompanySeed])
    inserted = 0
    updated = 0
    skipped = 0
    for payload in initial_company_seeds():
        existing = await CompanySeed.find_one(CompanySeed.domain == payload["domain"])
        if existing:
            changed = False
            for key, value in payload.items():
                if key == "added_by":
                    continue
                if getattr(existing, key, None) != value:
                    setattr(existing, key, value)
                    changed = True
            if changed:
                existing.updated_at = utc_now()
                await existing.save()
                updated += 1
            else:
                skipped += 1
            continue
        try:
            await CompanySeed(**payload).insert()
            inserted += 1
        except DuplicateKeyError:
            skipped += 1
    client.close()
    return {"inserted": inserted, "updated": updated, "skipped": skipped, "total": inserted + updated + skipped}


if __name__ == "__main__":
    print(asyncio.run(bootstrap_company_seeds()))
