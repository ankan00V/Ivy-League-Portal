import spacy
from transformers import pipeline

class AIEngine:
    def __init__(self):
        self.nlp = None
        self.classifier = None
        
        # Define categories matching our domains
        self.domains = [
            "AI and Machine Learning",
            "Law",
            "Biomedical and Healthcare",
            "Engineering",
            "Finance",
            "Data Science"
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
        }

    def _init_models(self):
        """Lazy load heavy ML models to prevent Uvicorn startup hangs"""
        if self.nlp is None:
            try:
                self.nlp = spacy.load("en_core_web_sm")
            except:
                import os
                os.system("python -m spacy download en_core_web_sm")
                self.nlp = spacy.load("en_core_web_sm")
                
        if self.classifier is None:
            self.classifier = pipeline("zero-shot-classification", model="valhalla/distilbart-mnli-12-3")

    def classify_opportunity(self, text: str) -> dict:
        """
        Classifies an opportunity text into one or more domains with confidence scores.
        """
        if not text.strip():
            return {"primary_domain": "General", "scores": {}}

        lowered = text.lower()
        scored_domains: list[tuple[str, float]] = []
        for domain, keywords in self.domain_keywords.items():
            hits = 0
            for keyword in keywords:
                if keyword in lowered:
                    hits += 1
            if hits:
                scored_domains.append((domain, min(0.95, 0.25 + hits * 0.18)))

        if scored_domains:
            scored_domains.sort(key=lambda item: item[1], reverse=True)
            return {
                "primary_domain": scored_domains[0][0],
                "relevant_domains": {domain: round(score, 2) for domain, score in scored_domains},
            }

        return {
            "primary_domain": "Engineering",
            "relevant_domains": {"Engineering": 0.45},
        }

    def parse_resume(self, text: str) -> dict:
        """
        Parses resume text to extract skills, education, and calculate basic InCoScore.
        """
        self._init_models()
        
        doc = self.nlp(text)
        
        # Naive extraction - in a real production system we'd use custom NER
        entities = {"ORG": [], "EDU": [], "SKILLS": []}
        
        for ent in doc.ents:
            if ent.label_ == "ORG":
                entities["ORG"].append(ent.text)
            elif ent.label_ == "DATE":
                # often education dates
                pass
                
        # Basic keyword matching for skills
        skill_keywords = ["Python", "Java", "C++", "React", "Node", "SQL", "Machine Learning", "Data Analysis", "Research"]
        extracted_skills = [s for s in skill_keywords if s.lower() in text.lower()]
        
        return {
            "organizations": list(set(entities["ORG"])),
            "skills": extracted_skills,
            "raw_text_length": len(text)
        }

# Singleton instance
ai_system = AIEngine()
