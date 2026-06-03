from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

from beanie import init_beanie
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import DuplicateKeyError

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import settings  # noqa: E402
from app.models.source_discovery import CompanySeed  # noqa: E402


def _seed(
    company_name: str,
    domain: str,
    industry: str,
    company_size: str,
    *,
    careers_url: str | None = None,
    india_presence: bool = True,
    student_friendly: bool = True,
) -> dict[str, Any]:
    return {
        "company_name": company_name,
        "domain": domain,
        "careers_url": careers_url,
        "industry": industry,
        "company_size": company_size,
        "india_presence": india_presence,
        "student_friendly": student_friendly,
        "added_by": "bootstrap",
    }


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
    for item in RAW_SEEDS:
        domain = str(item["domain"]).lower().removeprefix("www.")
        if domain in seen:
            continue
        seen.add(domain)
        item["domain"] = domain
        rows.append(item)
        if len(rows) >= 200:
            break
    return rows


async def bootstrap_company_seeds() -> dict[str, int]:
    client = AsyncIOMotorClient(settings.MONGODB_URL)
    await init_beanie(database=client[settings.MONGODB_DB_NAME], document_models=[CompanySeed])
    inserted = 0
    skipped = 0
    for payload in initial_company_seeds():
        if await CompanySeed.find_one(CompanySeed.domain == payload["domain"]):
            skipped += 1
            continue
        try:
            await CompanySeed(**payload).insert()
            inserted += 1
        except DuplicateKeyError:
            skipped += 1
    client.close()
    return {"inserted": inserted, "skipped": skipped, "total": inserted + skipped}


if __name__ == "__main__":
    print(asyncio.run(bootstrap_company_seeds()))
