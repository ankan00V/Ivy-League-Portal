import re
from datetime import datetime
from app.core.time import utc_now

class AIEngine:
    def __init__(self):
        self.nlp = None
        self.classifier = None
        
        # Define categories matching our domains
        # Six domains, all technical or professional, meant every non-technical
        # role landed in the Engineering bucket - a travel consultant, an HR
        # intern and a digital marketing intern were all labelled Engineering,
        # which is worse than no label because a student filters on it.
        self.domains = [
            "AI and Machine Learning",
            "Law",
            "Biomedical and Healthcare",
            "Engineering",
            "Finance",
            "Data Science",
            "Marketing",
            "Business and Operations",
            "Sales and Support",
            "Human Resources",
            "Design and Creative",
            "Education",
            "Other",
        ]
        self.domain_keywords = {
            "AI and Machine Learning": {
                "ai", "ml", "machine learning", "deep learning", "neural", "nlp",
                "llm", "genai", "generative ai", "computer vision", "artificial intelligence",
            },
            "Law": {
                "law", "legal", "compliance", "litigation", "policy", "moot",
                "advocate", "contract", "jurisprudence", "regulatory",
            },
            "Biomedical and Healthcare": {
                "biomedical", "healthcare", "medical", "medicine", "clinical",
                "biotech", "biotechnology", "pharma", "public health", "genomics",
            },
            "Engineering": {
                "engineering", "engineer", "developer", "software", "web",
                "backend", "frontend", "full stack", "fullstack", "hackathon",
                "coding", "robotics", "cybersecurity", "cloud", "devops",
                "mechanical", "civil", "electrical", "embedded",
            },
            "Finance": {
                "finance", "financial", "fintech", "banking", "investment",
                "trading", "accounting", "economics", "audit", "quant",
            },
            "Data Science": {
                "data science", "data scientist", "analytics", "analysis",
                "statistical", "statistics", "sql", "power bi", "tableau",
                "business intelligence", "data engineering", "data engineer",
            },
            "Marketing": {
                "marketing", "seo", "sem", "brand", "branding", "advertising",
                "campaign", "growth marketing", "digital marketing", "content marketing",
                "social media", "copywriting", "public relations", "communications",
            },
            "Business and Operations": {
                "business analyst", "operations", "strategy", "consultant", "consulting",
                "program manager", "project manager", "supply chain", "logistics",
                "procurement", "travel consultant", "administration", "coordinator",
            },
            "Sales and Support": {
                "sales", "business development", "account executive", "account manager",
                "customer success", "customer support", "customer service", "pre-sales",
                "inside sales", "retention", "telecalling", "client servicing",
            },
            "Human Resources": {
                "human resources", "hr ", "recruitment", "recruiter", "talent acquisition",
                "people operations", "payroll", "onboarding", "hr intern", "hr consultant",
            },
            "Design and Creative": {
                "designer", "design intern", "ux", "ui/ux", "graphic design", "visual design",
                "product design", "illustrator", "figma", "video editing", "animation",
                "photography", "creative",
            },
            "Education": {
                "teaching", "tutor", "educator", "curriculum", "edtech", "academic",
                "instructional", "trainer", "faculty", "lecturer",
            },
        }

    def _ensure_nlp(self):
        """Lazy load spaCy model to prevent startup hangs."""
        if self.nlp is None:
            import spacy

            try:
                self.nlp = spacy.load("en_core_web_sm")
            except Exception:
                self.nlp = spacy.blank("en")
        return self.nlp

    def _ensure_classifier(self):
        """Lazy load classifier only when required."""
        if self.classifier is None:
            # Import transformers lazily to avoid expensive model stack loading
            # during API boot when OTP/auth routes are the only immediate need.
            from transformers import pipeline

            self.classifier = pipeline("zero-shot-classification", model="valhalla/distilbart-mnli-12-3")
        return self.classifier

    def _init_models(self):
        """Backward-compatible initializer for callers expecting both models."""
        self._ensure_nlp()
        self._ensure_classifier()

    def classify_opportunity(self, text: str, title: str | None = None) -> dict:
        """Score domains, weighting the title far above the body.

        Scoring the title and description as one blob let the body decide: a
        marketing internship whose description mentioned the engineering team
        scored Engineering, and a travel consultant role scored it too. The
        title is what the employer calls the job, so a keyword there counts for
        several times one buried in the body.

        The fallback is "Other" rather than Engineering. Defaulting to a real
        domain mislabels every unrecognised role as technical, which is exactly
        how non-technical listings ended up filed as Engineering.
        """
        if not str(text or "").strip() and not str(title or "").strip():
            return {"primary_domain": "Other", "relevant_domains": {}}

        # When no title is passed the first line is the best available proxy.
        body = str(text or "").lower()
        head = str(title if title is not None else body.split("\n", 1)[0][:160]).lower()

        TITLE_WEIGHT = 5
        scored_domains: list[tuple[str, float]] = []
        for domain, keywords in self.domain_keywords.items():
            score = 0
            for keyword in keywords:
                if keyword in head:
                    score += TITLE_WEIGHT
                elif keyword in body:
                    score += 1
            if score:
                scored_domains.append((domain, min(0.95, 0.25 + score * 0.06)))

        if scored_domains:
            scored_domains.sort(key=lambda item: item[1], reverse=True)
            return {
                "primary_domain": scored_domains[0][0],
                "relevant_domains": {domain: round(score, 2) for domain, score in scored_domains},
            }

        return {"primary_domain": "Other", "relevant_domains": {"Other": 0.4}}

    def parse_resume(self, text: str) -> dict:
        """
        Parses resume text and returns structured hints for profile auto-fill.
        """
        cleaned = (text or "").strip()
        if not cleaned:
            return {
                "organizations": [],
                "skills": [],
                "education": "",
                "course": None,
                "college_name": None,
                "inferred_domain": None,
                "current_job_role": None,
                "years_of_experience": None,
                "total_work_experience": None,
                "passout_year": None,
                "user_type_hint": None,
                "raw_text_length": 0,
            }

        nlp = self._ensure_nlp()
        doc = nlp(cleaned)
        lowered = cleaned.lower()

        def _dedupe(values: list[str]) -> list[str]:
            seen: set[str] = set()
            output: list[str] = []
            for value in values:
                item = (value or "").strip()
                if not item:
                    continue
                key = item.lower()
                if key in seen:
                    continue
                seen.add(key)
                output.append(item)
            return output

        organizations = _dedupe([ent.text for ent in getattr(doc, "ents", []) if ent.label_ == "ORG"])

        skill_patterns: list[tuple[str, str]] = [
            (r"\bpython\b", "Python"),
            (r"\bjava\b", "Java"),
            (r"\bc\+\+\b", "C++"),
            (r"\bjavascript\b", "JavaScript"),
            (r"\btypescript\b", "TypeScript"),
            (r"\breact\b", "React"),
            (r"\bnode(?:\.js)?\b", "Node.js"),
            (r"\bfastapi\b", "FastAPI"),
            (r"\bdjango\b", "Django"),
            (r"\bflask\b", "Flask"),
            (r"\bsql\b", "SQL"),
            (r"\bmysql\b", "MySQL"),
            (r"\bpostgres(?:ql)?\b", "PostgreSQL"),
            (r"\bmongodb\b", "MongoDB"),
            (r"\bredis\b", "Redis"),
            (r"\bpandas\b", "Pandas"),
            (r"\bnumpy\b", "NumPy"),
            (r"\bscikit[- ]?learn\b", "Scikit-learn"),
            (r"\btensorflow\b", "TensorFlow"),
            (r"\bpytorch\b", "PyTorch"),
            (r"\bmachine learning\b", "Machine Learning"),
            (r"\bdeep learning\b", "Deep Learning"),
            (r"\bdata science\b", "Data Science"),
            (r"\bdata analysis\b", "Data Analysis"),
            (r"\bstatistics?\b", "Statistics"),
            (r"\bpower ?bi\b", "Power BI"),
            (r"\btableau\b", "Tableau"),
            (r"\bexcel\b", "Excel"),
            (r"\baws\b", "AWS"),
            (r"\bazure\b", "Azure"),
            (r"\bgcp\b", "GCP"),
            (r"\bdocker\b", "Docker"),
            (r"\bkubernetes\b", "Kubernetes"),
            (r"\bgen(?:erative)? ?ai\b", "Generative AI"),
            (r"\bllm(?:s)?\b", "LLMs"),
            (r"\bnlp\b", "NLP"),
            (r"\bcomputer vision\b", "Computer Vision"),
            (r"\bprompt engineering\b", "Prompt Engineering"),
            (r"\bstreamlit\b", "Streamlit"),
        ]
        extracted_skills = [label for pattern, label in skill_patterns if re.search(pattern, lowered, flags=re.IGNORECASE)]
        extracted_skills = _dedupe(extracted_skills)

        education_lines: list[str] = []
        for raw_line in re.split(r"[\r\n]+", cleaned):
            line = raw_line.strip()
            if not line:
                continue
            if re.search(
                r"\b(b\.?tech|bachelor|m\.?tech|master|mca|bca|mba|ph\.?d|degree|university|college|institute|school)\b",
                line,
                flags=re.IGNORECASE,
            ):
                education_lines.append(line)
        education_lines = _dedupe(education_lines)[:3]
        education_summary = " | ".join(education_lines)

        course = None
        course_map = [
            ("B.Tech", r"\b(b\.?tech|bachelor of technology|b\.?e\b|be )"),
            ("M.Tech", r"\b(m\.?tech|master of technology)\b"),
            ("BCA", r"\bbca\b"),
            ("MCA", r"\bmca\b"),
            ("B.Sc", r"\bb\.?sc\b"),
            ("M.Sc", r"\bm\.?sc\b"),
            ("MBA", r"\bmba\b"),
        ]
        for label, pattern in course_map:
            if re.search(pattern, lowered, flags=re.IGNORECASE):
                course = label
                break

        passout_year: int | None = None
        passout_match = re.search(
            r"(?:pass(?:ing|ed)?\s*out|graduat(?:e|ed|ion)|batch|class of|expected)\D{0,12}(20\d{2})",
            lowered,
            flags=re.IGNORECASE,
        )
        if passout_match:
            passout_year = int(passout_match.group(1))
        else:
            years = [int(value) for value in re.findall(r"\b(20\d{2})\b", lowered)]
            if years:
                current_year = utc_now().year
                plausible = [year for year in years if current_year - 12 <= year <= current_year + 8]
                if plausible:
                    passout_year = max(plausible)

        exp_years: float | None = None
        year_matches = [float(value) for value in re.findall(r"(\d+(?:\.\d+)?)\s*\+?\s*(?:years?|yrs?)\b", lowered)]
        month_matches = [float(value) for value in re.findall(r"(\d+(?:\.\d+)?)\s*(?:months?|mos?)\b", lowered)]
        if year_matches:
            exp_years = max(year_matches)
        elif month_matches:
            exp_years = round(max(month_matches) / 12.0, 1)

        inferred_role = None
        role_patterns = [
            ("Data Scientist", r"\bdata scientist\b"),
            ("Machine Learning Engineer", r"\b(machine learning engineer|ml engineer)\b"),
            ("Data Analyst", r"\bdata analyst\b"),
            ("Software Engineer", r"\bsoftware engineer\b"),
            ("Full Stack Developer", r"\bfull ?stack (developer|engineer)\b"),
            ("Backend Developer", r"\bbackend (developer|engineer)\b"),
            ("Frontend Developer", r"\bfrontend (developer|engineer)\b"),
            ("Product Manager", r"\bproduct manager\b"),
            ("Research Intern", r"\bresearch intern\b"),
            ("Intern", r"\bintern(ship)?\b"),
        ]
        for label, pattern in role_patterns:
            if re.search(pattern, lowered, flags=re.IGNORECASE):
                inferred_role = label
                break

        domain_scores: dict[str, int] = {}
        for domain, keywords in self.domain_keywords.items():
            hits = 0
            for keyword in keywords:
                if keyword.lower() in lowered:
                    hits += 1
            if hits:
                domain_scores[domain] = hits
        inferred_domain = None
        if domain_scores:
            inferred_domain = max(domain_scores.items(), key=lambda item: item[1])[0]

        college_name = None
        for org in organizations:
            if re.search(r"\b(university|college|institute|school|iit|nit|iiit|iim)\b", org, flags=re.IGNORECASE):
                college_name = org
                break

        user_type_hint = None
        current_year = utc_now().year
        if exp_years is not None and exp_years >= 1:
            user_type_hint = "professional"
        elif passout_year is not None:
            user_type_hint = "college_student" if passout_year > current_year else "fresher"
        elif re.search(r"\b(student|undergraduate|college|university)\b", lowered):
            user_type_hint = "college_student"

        total_work_experience = None
        if exp_years is not None:
            total_work_experience = f"{exp_years:g} years"

        return {
            "organizations": organizations,
            "skills": extracted_skills,
            "education": education_summary,
            "course": course,
            "college_name": college_name,
            "inferred_domain": inferred_domain,
            "current_job_role": inferred_role,
            "years_of_experience": exp_years,
            "total_work_experience": total_work_experience,
            "passout_year": passout_year,
            "user_type_hint": user_type_hint,
            "raw_text_length": len(cleaned),
        }

# Singleton instance
ai_system = AIEngine()
