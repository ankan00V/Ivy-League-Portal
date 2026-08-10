#!/usr/bin/env python3
"""Generate VidyaVerse skills taxonomy exports.

The source lists and templates in this file are original, deterministic, and
intended for product autocomplete/search data generation.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path


TARGET_COUNT = 60000
REPO_ROOT = Path(__file__).resolve().parents[2]
# Only the two files the frontend actually fetches belong under public/,
# because everything there is world-readable over HTTP. The bulk exports
# (a 47MB .sql dump among them) were being served at
# /data/skills-taxonomy/skills.sql and copied into the standalone build.
PUBLIC_DIR = REPO_ROOT / "frontend" / "public" / "data" / "skills-taxonomy"
OUTPUT_DIR = REPO_ROOT / "data" / "skills-taxonomy"


STOP_SKILL_TERMS = {
    "bachelor",
    "master",
    "mba",
    "phd",
    "doctor",
    "engineer",
    "manager",
    "director",
    "executive",
    "specialist",
    "associate",
    "consultant",
    "intern",
    "professor",
    "teacher",
    "analyst",
    "architect",
    "certified",
    "certification",
    "degree",
    "diploma",
    "license",
}


@dataclass(frozen=True)
class CategorySpec:
    name: str
    subcategories: tuple[str, ...]
    parent: str
    technical: bool
    soft: bool = False


@dataclass
class SkillSeed:
    name: str
    category: str
    subcategory: str
    parent: str
    aliases: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    description: str = ""
    technical: bool = False
    soft: bool = False
    popularity: int = 50


CATEGORIES: tuple[CategorySpec, ...] = (
    CategorySpec("Programming Languages", ("General Purpose", "Systems", "Scripting", "Statistical", "Markup and Query"), "Programming Languages", True),
    CategorySpec("Frontend Development", ("Frameworks", "State Management", "Styling", "Build Tools", "Accessibility"), "Web Development", True),
    CategorySpec("Backend Development", ("Frameworks", "APIs", "Runtime Platforms", "Microservices", "Messaging"), "Software Engineering", True),
    CategorySpec("Mobile Development", ("Android", "iOS", "Cross Platform", "Mobile Testing", "Mobile UI"), "Mobile Development", True),
    CategorySpec("Game Development", ("Engines", "Rendering", "Gameplay Systems", "Physics", "Tools"), "Game Development", True),
    CategorySpec("Cloud Technologies", ("AWS", "Azure", "Google Cloud", "Serverless", "Cloud Architecture"), "Cloud Computing", True),
    CategorySpec("DevOps", ("Containers", "CI/CD", "Infrastructure as Code", "Observability", "Release Engineering"), "DevOps", True),
    CategorySpec("Databases", ("Relational", "NoSQL", "Search", "Graph", "Data Warehousing"), "Databases", True),
    CategorySpec("Data Engineering", ("Pipelines", "Streaming", "Orchestration", "Lakehouse", "ETL"), "Data Engineering", True),
    CategorySpec("Data Science", ("Analytics", "Statistics", "Visualization", "Experimentation", "Modeling"), "Data Science", True),
    CategorySpec("AI & Machine Learning", ("Machine Learning", "Deep Learning", "NLP", "Computer Vision", "Generative AI"), "Machine Learning", True),
    CategorySpec("MLOps", ("Model Registry", "Feature Stores", "Monitoring", "Deployment", "Evaluation"), "MLOps", True),
    CategorySpec("Cybersecurity", ("Application Security", "Network Security", "Identity Security", "Cloud Security", "Security Operations"), "Cybersecurity", True),
    CategorySpec("Networking", ("Protocols", "Routing", "Wireless", "Load Balancing", "Network Automation"), "Networking", True),
    CategorySpec("Operating Systems", ("Linux", "Windows", "macOS", "Unix", "Administration"), "Operating Systems", True),
    CategorySpec("Software Architecture", ("System Design", "Distributed Systems", "Design Patterns", "Scalability", "Reliability"), "Software Architecture", True),
    CategorySpec("Testing & QA", ("Automated Testing", "Manual Testing", "Performance Testing", "Security Testing", "Quality Processes"), "Quality Assurance", True),
    CategorySpec("UI/UX Design", ("User Research", "Interaction Design", "Visual Design", "Prototyping", "Design Systems"), "Design", False),
    CategorySpec("Design & Creative Tools", ("Graphic Design", "CAD", "Animation", "Video", "Audio"), "Creative Production", True),
    CategorySpec("Product Management", ("Discovery", "Roadmapping", "Metrics", "Go-to-Market", "Lifecycle"), "Product Management", False),
    CategorySpec("Project Management", ("Agile", "Planning", "Risk", "Delivery", "Stakeholder Management"), "Project Management", False),
    CategorySpec("Business Analysis", ("Requirements", "Process Modeling", "Documentation", "Decision Analysis", "Operations Analysis"), "Business Analysis", False),
    CategorySpec("Finance", ("Accounting", "Corporate Finance", "Investment", "Banking", "Risk Management"), "Finance", False),
    CategorySpec("Marketing", ("Digital Marketing", "SEO", "Content Marketing", "Branding", "Growth"), "Marketing", False),
    CategorySpec("Sales", ("Prospecting", "Account Management", "Sales Operations", "Negotiation", "Revenue Operations"), "Sales", False),
    CategorySpec("Human Resources", ("Recruitment", "Talent Management", "Learning", "Compensation", "Employee Relations"), "Human Resources", False),
    CategorySpec("Legal", ("Contracts", "Compliance", "Privacy", "Intellectual Property", "Legal Operations"), "Legal", False),
    CategorySpec("Healthcare", ("Clinical Operations", "Healthcare Analytics", "Public Health", "Medical Documentation", "Health Informatics"), "Healthcare", False),
    CategorySpec("Biotechnology", ("Molecular Biology", "Bioinformatics", "Bioprocessing", "Genomics", "Laboratory Methods"), "Biotechnology", True),
    CategorySpec("Engineering", ("Mechanical", "Electrical", "Civil", "Electronics", "Aerospace"), "Engineering", True),
    CategorySpec("Manufacturing", ("Lean", "Quality", "Production", "Maintenance", "Industrial Automation"), "Manufacturing", True),
    CategorySpec("Supply Chain & Logistics", ("Procurement", "Warehousing", "Transportation", "Inventory", "Planning"), "Supply Chain", False),
    CategorySpec("Education", ("Instructional Design", "Assessment", "Curriculum", "EdTech", "Training"), "Education", False),
    CategorySpec("Agriculture", ("Crop Science", "AgriTech", "Soil Science", "Irrigation", "Farm Operations"), "Agriculture", True),
    CategorySpec("Media & Communication", ("Writing", "Editing", "Journalism", "Public Relations", "Translation"), "Communication", False),
    CategorySpec("Soft Skills", ("Communication", "Leadership", "Thinking", "Collaboration", "Personal Effectiveness"), "Workplace Competencies", False, True),
    CategorySpec("Industry Domain Skills", ("Retail", "Insurance", "Telecommunications", "Hospitality", "Government"), "Industry Knowledge", False),
)


TECH_SEEDS: tuple[SkillSeed, ...] = (
    SkillSeed("Python", "Programming Languages", "General Purpose", "Programming Languages", ["python3", "py"], ["coding", "automation", "backend"], "High-level general-purpose programming language.", True, False, 99),
    SkillSeed("JavaScript", "Programming Languages", "Scripting", "Programming Languages", ["js", "javascript"], ["frontend", "web"], "Language for interactive web and server applications.", True, False, 98),
    SkillSeed("TypeScript", "Programming Languages", "General Purpose", "Programming Languages", ["ts", "typescript"], ["typed javascript", "frontend"], "Typed superset of JavaScript for scalable applications.", True, False, 96),
    SkillSeed("C++", "Programming Languages", "Systems", "Programming Languages", ["cpp", "cplusplus", "c plus plus"], ["systems", "game development"], "Compiled language for high-performance systems software.", True, False, 92),
    SkillSeed("C#", "Programming Languages", "General Purpose", "Programming Languages", ["c sharp", "csharp"], ["dotnet", "unity"], "Object-oriented language for .NET and Unity applications.", True, False, 88),
    SkillSeed("Java", "Programming Languages", "General Purpose", "Programming Languages", [], ["jvm", "backend"], "Object-oriented language for cross-platform applications.", True, False, 94),
    SkillSeed("Go", "Programming Languages", "Systems", "Programming Languages", ["golang"], ["cloud", "backend"], "Compiled language for networked and cloud services.", True, False, 88),
    SkillSeed("Rust", "Programming Languages", "Systems", "Programming Languages", [], ["systems", "memory safety"], "Systems language focused on safety and performance.", True, False, 86),
    SkillSeed("SQL", "Programming Languages", "Markup and Query", "Programming Languages", ["structured query language"], ["database", "query"], "Language for querying and managing relational data.", True, False, 98),
    SkillSeed("React", "Frontend Development", "Frameworks", "Web Development", ["reactjs", "react.js"], ["frontend", "components"], "JavaScript library for component-based user interfaces.", True, False, 97),
    SkillSeed("Next.js", "Frontend Development", "Frameworks", "Web Development", ["nextjs", "next"], ["react", "full stack"], "React framework for server-rendered web applications.", True, False, 94),
    SkillSeed("Angular", "Frontend Development", "Frameworks", "Web Development", ["angularjs"], ["frontend", "typescript"], "Framework for structured web applications.", True, False, 88),
    SkillSeed("Vue.js", "Frontend Development", "Frameworks", "Web Development", ["vue", "vuejs"], ["frontend"], "Progressive framework for building web interfaces.", True, False, 87),
    SkillSeed("Node.js", "Backend Development", "Runtime Platforms", "Software Engineering", ["nodejs", "node"], ["javascript runtime", "backend"], "JavaScript runtime for server-side applications.", True, False, 96),
    SkillSeed("Express", "Backend Development", "Frameworks", "Software Engineering", ["express.js", "expressjs"], ["node", "api"], "Minimal web framework for Node.js services.", True, False, 91),
    SkillSeed("FastAPI", "Backend Development", "Frameworks", "Software Engineering", ["fast api"], ["python", "api"], "Python framework for high-performance APIs.", True, False, 91),
    SkillSeed("Django", "Backend Development", "Frameworks", "Software Engineering", [], ["python", "web"], "Python framework for secure web applications.", True, False, 90),
    SkillSeed("Flask", "Backend Development", "Frameworks", "Software Engineering", [], ["python", "api"], "Lightweight Python framework for web services.", True, False, 86),
    SkillSeed("Spring Boot", "Backend Development", "Frameworks", "Software Engineering", ["springboot"], ["java", "microservices"], "Java framework for production-grade services.", True, False, 91),
    SkillSeed("PostgreSQL", "Databases", "Relational", "Databases", ["postgres", "postgresql"], ["sql", "database"], "Open-source relational database system.", True, False, 95),
    SkillSeed("MongoDB", "Databases", "NoSQL", "Databases", ["mongo"], ["document database"], "Document database for flexible data models.", True, False, 92),
    SkillSeed("Redis", "Databases", "NoSQL", "Databases", [], ["cache", "key value"], "In-memory data store for caching and queues.", True, False, 93),
    SkillSeed("Apache Kafka", "Data Engineering", "Streaming", "Data Engineering", ["kafka"], ["event streaming"], "Distributed event streaming platform.", True, False, 92),
    SkillSeed("Apache Spark", "Data Engineering", "Pipelines", "Data Engineering", ["spark", "pyspark"], ["big data"], "Distributed engine for large-scale data processing.", True, False, 91),
    SkillSeed("Docker", "DevOps", "Containers", "DevOps", [], ["containers"], "Platform for building and running containers.", True, False, 96),
    SkillSeed("Kubernetes", "DevOps", "Containers", "DevOps", ["k8s"], ["orchestration"], "Container orchestration platform for distributed workloads.", True, False, 95),
    SkillSeed("Terraform", "DevOps", "Infrastructure as Code", "DevOps", [], ["iac", "cloud"], "Infrastructure as code tool for provisioning resources.", True, False, 92),
    SkillSeed("Git", "DevOps", "Release Engineering", "DevOps", [], ["version control"], "Distributed version control system.", True, False, 99),
    SkillSeed("GitHub Actions", "DevOps", "CI/CD", "DevOps", ["github workflows"], ["automation", "ci cd"], "Automation platform for CI/CD workflows.", True, False, 91),
    SkillSeed("AWS Lambda", "Cloud Technologies", "Serverless", "Cloud Computing", ["lambda"], ["serverless", "aws"], "Serverless compute service for event-driven workloads.", True, False, 88),
    SkillSeed("Amazon S3", "Cloud Technologies", "AWS", "Cloud Computing", ["s3"], ["object storage", "aws"], "Object storage service for cloud applications.", True, False, 92),
    SkillSeed("Azure Functions", "Cloud Technologies", "Serverless", "Cloud Computing", [], ["serverless", "azure"], "Serverless compute service on Azure.", True, False, 83),
    SkillSeed("Google BigQuery", "Databases", "Data Warehousing", "Databases", ["bigquery"], ["warehouse", "analytics"], "Cloud data warehouse for analytical workloads.", True, False, 90),
    SkillSeed("Snowflake", "Databases", "Data Warehousing", "Databases", [], ["data warehouse"], "Cloud data platform for analytics workloads.", True, False, 91),
    SkillSeed("Databricks", "Data Engineering", "Lakehouse", "Data Engineering", [], ["lakehouse", "spark"], "Lakehouse platform for data engineering and ML.", True, False, 90),
    SkillSeed("dbt", "Data Engineering", "ETL", "Data Engineering", ["data build tool"], ["transformations", "analytics engineering"], "Tool for SQL-based data transformation workflows.", True, False, 90),
    SkillSeed("Apache Airflow", "Data Engineering", "Orchestration", "Data Engineering", ["airflow"], ["workflow orchestration"], "Platform for scheduling and monitoring data pipelines.", True, False, 91),
    SkillSeed("TensorFlow", "AI & Machine Learning", "Deep Learning", "Machine Learning", ["tf", "tensor flow"], ["deep learning"], "Framework for training and deploying ML models.", True, False, 92),
    SkillSeed("PyTorch", "AI & Machine Learning", "Deep Learning", "Machine Learning", ["torch"], ["deep learning"], "Deep learning framework with dynamic computation graphs.", True, False, 95),
    SkillSeed("JAX", "AI & Machine Learning", "Deep Learning", "Machine Learning", [], ["autodiff", "accelerated computing"], "Python library for composable automatic differentiation.", True, False, 82),
    SkillSeed("ONNX", "MLOps", "Deployment", "MLOps", [], ["model interchange"], "Open format for interoperable machine learning models.", True, False, 82),
    SkillSeed("MLflow", "MLOps", "Model Registry", "MLOps", [], ["experiments", "model registry"], "Platform for tracking and managing ML lifecycle.", True, False, 88),
    SkillSeed("LangChain", "AI & Machine Learning", "Generative AI", "Machine Learning", [], ["llm", "agents", "rag"], "Framework for building LLM-powered applications.", True, False, 90),
    SkillSeed("LangGraph", "AI & Machine Learning", "Generative AI", "Machine Learning", [], ["llm agents", "agent workflows"], "Framework for stateful agent workflows.", True, False, 85),
    SkillSeed("CrewAI", "AI & Machine Learning", "Generative AI", "Machine Learning", ["crew ai"], ["multi agent"], "Framework for orchestrating collaborative AI agents.", True, False, 78),
    SkillSeed("AutoGen", "AI & Machine Learning", "Generative AI", "Machine Learning", ["autogen"], ["multi agent"], "Framework for multi-agent AI conversations.", True, False, 78),
    SkillSeed("OpenAI Agents SDK", "AI & Machine Learning", "Generative AI", "Machine Learning", ["agents sdk"], ["agentic ai"], "SDK for building agentic AI applications.", True, False, 86),
    SkillSeed("LlamaIndex", "AI & Machine Learning", "Generative AI", "Machine Learning", ["llama index"], ["rag"], "Framework for connecting data to LLM applications.", True, False, 88),
    SkillSeed("Haystack", "AI & Machine Learning", "NLP", "Machine Learning", [], ["rag", "search"], "Framework for search and question answering systems.", True, False, 77),
    SkillSeed("vLLM", "MLOps", "Deployment", "MLOps", ["vllm"], ["llm serving"], "High-throughput inference engine for language models.", True, False, 86),
    SkillSeed("Ollama", "AI & Machine Learning", "Generative AI", "Machine Learning", [], ["local llm"], "Tool for running local language models.", True, False, 86),
    SkillSeed("ComfyUI", "AI & Machine Learning", "Generative AI", "Machine Learning", ["comfy ui"], ["image generation"], "Node-based interface for generative image workflows.", True, False, 82),
    SkillSeed("Hugging Face Transformers", "AI & Machine Learning", "NLP", "Machine Learning", ["transformers"], ["nlp", "llm"], "Library for transformer-based machine learning models.", True, False, 92),
    SkillSeed("Ray", "Data Engineering", "Pipelines", "Data Engineering", [], ["distributed computing"], "Framework for distributed Python and AI workloads.", True, False, 84),
    SkillSeed("Apache Iceberg", "Data Engineering", "Lakehouse", "Data Engineering", ["iceberg"], ["table format"], "Open table format for large analytical datasets.", True, False, 84),
    SkillSeed("Delta Lake", "Data Engineering", "Lakehouse", "Data Engineering", ["delta"], ["lakehouse"], "Storage layer for reliable lakehouse tables.", True, False, 86),
    SkillSeed("Tableau", "Data Science", "Visualization", "Data Science", [], ["dashboard", "bi"], "Business intelligence tool for visual analytics.", True, False, 92),
    SkillSeed("Power BI", "Data Science", "Visualization", "Data Science", ["powerbi"], ["dashboard", "bi"], "Business intelligence platform for interactive reporting.", True, False, 94),
    SkillSeed("Microsoft Excel", "Finance", "Accounting", "Finance", ["excel", "ms excel"], ["spreadsheet", "analysis"], "Spreadsheet tool for analysis and reporting.", True, False, 98),
    SkillSeed("Figma", "UI/UX Design", "Prototyping", "Design", [], ["design", "prototype"], "Collaborative interface design and prototyping tool.", True, False, 94),
    SkillSeed("Adobe Photoshop", "Design & Creative Tools", "Graphic Design", "Creative Production", ["photoshop"], ["image editing"], "Image editing and compositing software.", True, False, 90),
    SkillSeed("Adobe Illustrator", "Design & Creative Tools", "Graphic Design", "Creative Production", ["illustrator"], ["vector design"], "Vector graphics and illustration software.", True, False, 86),
    SkillSeed("AutoCAD", "Design & Creative Tools", "CAD", "Creative Production", ["autocad"], ["cad"], "Computer-aided design software for drafting.", True, False, 88),
    SkillSeed("MATLAB", "Data Science", "Modeling", "Data Science", ["matlab"], ["scientific computing"], "Numerical computing environment for analysis and modeling.", True, False, 84),
)


SOFT_SEEDS: tuple[SkillSeed, ...] = (
    SkillSeed("Communication", "Soft Skills", "Communication", "Workplace Competencies", ["communications"], ["workplace", "collaboration"], "Clear exchange of information with others.", False, True, 100),
    SkillSeed("Written Communication", "Soft Skills", "Communication", "Workplace Competencies", ["writing communication"], ["email", "documentation"], "Clear communication through written formats.", False, True, 98),
    SkillSeed("Verbal Communication", "Soft Skills", "Communication", "Workplace Competencies", ["spoken communication"], ["speaking"], "Clear communication through spoken interaction.", False, True, 98),
    SkillSeed("Active Listening", "Soft Skills", "Communication", "Workplace Competencies", [], ["listening", "empathy"], "Attentive listening that improves understanding.", False, True, 98),
    SkillSeed("Leadership", "Soft Skills", "Leadership", "Workplace Competencies", [], ["influence", "team direction"], "Guiding people toward shared outcomes.", False, True, 99),
    SkillSeed("Teamwork", "Soft Skills", "Collaboration", "Workplace Competencies", ["team work"], ["collaboration"], "Working effectively with others toward goals.", False, True, 99),
    SkillSeed("Collaboration", "Soft Skills", "Collaboration", "Workplace Competencies", [], ["cross functional"], "Coordinating work across people and teams.", False, True, 99),
    SkillSeed("Critical Thinking", "Soft Skills", "Thinking", "Workplace Competencies", [], ["reasoning"], "Evaluating information to form sound judgments.", False, True, 98),
    SkillSeed("Problem Solving", "Soft Skills", "Thinking", "Workplace Competencies", ["problem-solving"], ["troubleshooting"], "Identifying causes and creating effective solutions.", False, True, 99),
    SkillSeed("Adaptability", "Soft Skills", "Personal Effectiveness", "Workplace Competencies", [], ["flexibility"], "Adjusting effectively to changing conditions.", False, True, 97),
    SkillSeed("Time Management", "Soft Skills", "Personal Effectiveness", "Workplace Competencies", [], ["prioritization"], "Using time effectively to meet commitments.", False, True, 98),
    SkillSeed("Negotiation", "Soft Skills", "Communication", "Workplace Competencies", [], ["persuasion"], "Reaching agreements through structured discussion.", False, True, 94),
    SkillSeed("Public Speaking", "Soft Skills", "Communication", "Workplace Competencies", ["presentation speaking"], ["presentations"], "Speaking effectively to groups and audiences.", False, True, 94),
    SkillSeed("Emotional Intelligence", "Soft Skills", "Collaboration", "Workplace Competencies", ["eq"], ["self awareness", "empathy"], "Recognizing and managing emotions in work relationships.", False, True, 96),
    SkillSeed("Stakeholder Management", "Project Management", "Stakeholder Management", "Project Management", [], ["communication", "alignment"], "Managing expectations and alignment across stakeholders.", False, False, 93),
)


DOMAIN_TERMS = (
    "API", "Authentication", "Authorization", "Billing", "Caching", "Search", "Recommendation", "Personalization", "Workflow",
    "Event-Driven", "Real-Time", "Batch", "Streaming", "Data Quality", "Data Governance", "Metadata", "Feature Engineering",
    "Model Evaluation", "Model Serving", "Prompt", "Agent", "RAG", "Vector Search", "Computer Vision", "NLP", "Forecasting",
    "Anomaly Detection", "Fraud Detection", "Risk", "Compliance", "Privacy", "Threat Detection", "Incident Response",
    "Network", "Storage", "Database", "Schema", "Query", "Frontend", "Backend", "Mobile", "Embedded", "IoT", "Robotics",
    "PLC", "SCADA", "Control Systems", "Signal Processing", "Power Systems", "VLSI", "PCB", "Firmware", "FPGA", "CAD",
    "Finite Element", "Thermal", "Fluid Dynamics", "Structural", "Geotechnical", "Surveying", "BIM", "HVAC", "Quality",
    "Lean", "Six Sigma", "Maintenance", "Procurement", "Inventory", "Demand Planning", "Transportation", "Warehouse",
    "Clinical", "Healthcare", "Bioinformatics", "Genomics", "Proteomics", "Pharmacovigilance", "Laboratory", "Agronomy",
    "Irrigation", "Soil", "Crop", "Retail", "E-commerce", "Insurance", "Banking", "Tax", "Audit", "Budgeting", "Valuation",
    "SEO", "Content", "Brand", "Campaign", "CRM", "Sales Pipeline", "Customer Success", "Support", "Recruiting",
    "Learning", "Compensation", "Contract", "Accessibility", "Usability", "Design System", "Animation", "Video", "Audio",
    "Translation", "Localization", "Research", "Curriculum", "Assessment", "Instructional", "Hospitality", "Maritime",
    "Aviation", "Telecommunications", "Energy", "Renewable Energy", "Oil and Gas", "Mining", "Sports", "Entertainment",
)

METHOD_TERMS = (
    "Analysis", "Design", "Development", "Implementation", "Optimization", "Automation", "Testing", "Validation",
    "Monitoring", "Troubleshooting", "Governance", "Documentation", "Planning", "Forecasting", "Modeling", "Simulation",
    "Reporting", "Dashboarding", "Strategy", "Operations", "Integration", "Migration", "Administration", "Configuration",
    "Performance Tuning", "Security Review", "Quality Assurance", "Process Improvement", "Root Cause Analysis",
    "Requirements Gathering", "Stakeholder Alignment", "Change Management", "Risk Assessment", "Compliance Review",
    "Data Collection", "Data Cleaning", "Data Visualization", "Benchmarking", "Experimentation", "Workflow Mapping",
)

TOOLS_BY_CATEGORY: dict[str, tuple[str, ...]] = {
    "Frontend Development": ("Vite", "Webpack", "Babel", "ESLint", "Prettier", "Storybook", "Tailwind CSS", "Sass", "Redux", "Zustand", "TanStack Query", "Svelte", "Astro", "Remix", "Three.js", "D3.js"),
    "Backend Development": ("NestJS", "Koa", "Hapi", "Ruby on Rails", "Laravel", "Phoenix", "ASP.NET Core", "gRPC", "GraphQL", "REST APIs", "WebSockets", "Celery", "BullMQ", "Sidekiq", "RabbitMQ"),
    "Databases": ("MySQL", "MariaDB", "SQLite", "Oracle Database", "Microsoft SQL Server", "Cassandra", "DynamoDB", "Couchbase", "Neo4j", "Elasticsearch", "OpenSearch", "ClickHouse", "DuckDB", "TimescaleDB", "InfluxDB"),
    "Cloud Technologies": ("Amazon EC2", "Amazon ECS", "Amazon EKS", "AWS Glue", "AWS Step Functions", "AWS CloudFormation", "Azure Kubernetes Service", "Azure Blob Storage", "Azure Synapse", "Google Cloud Run", "Google Kubernetes Engine", "Google Cloud Storage", "Firebase"),
    "DevOps": ("Jenkins", "GitLab CI", "CircleCI", "Argo CD", "Flux CD", "Helm", "Packer", "Pulumi", "Prometheus", "Grafana", "OpenTelemetry", "Datadog", "Sentry", "Vault", "Consul"),
    "AI & Machine Learning": ("scikit-learn", "NumPy", "Pandas", "SciPy", "Keras", "XGBoost", "LightGBM", "CatBoost", "spaCy", "NLTK", "OpenCV", "Ultralytics YOLO", "Stable Diffusion", "Diffusers", "Sentence Transformers"),
    "Cybersecurity": ("OWASP ZAP", "Burp Suite", "Nmap", "Wireshark", "Metasploit", "Suricata", "Snort", "OSQuery", "YARA", "Sigma", "Splunk", "Wazuh", "Falco"),
    "Design & Creative Tools": ("Blender", "Maya", "Cinema 4D", "After Effects", "Premiere Pro", "DaVinci Resolve", "Final Cut Pro", "Logic Pro", "Ableton Live", "Pro Tools", "Revit", "SolidWorks", "CATIA", "Fusion 360", "QGIS", "ArcGIS"),
    "Finance": ("QuickBooks", "Xero", "Tally", "SAP FICO", "Oracle NetSuite", "Bloomberg Terminal", "Stripe", "Razorpay", "Zoho Books"),
    "Marketing": ("Google Analytics", "Google Search Console", "Google Ads", "Meta Ads", "HubSpot", "Mailchimp", "Semrush", "Ahrefs", "Moz", "Hootsuite", "Buffer"),
    "Sales": ("Salesforce", "HubSpot CRM", "Zoho CRM", "Pipedrive", "Gong", "Outreach", "Apollo", "LeadSquared"),
    "Human Resources": ("Workday", "Greenhouse", "Lever", "Ashby", "BambooHR", "Darwinbox", "Keka", "LinkedIn Recruiter"),
}


def normalize_key(value: str) -> str:
    return re.sub(r"[^a-z0-9+#.]+", " ", value.lower()).strip()


def compact_alias(value: str) -> str:
    return re.sub(r"[^a-z0-9+#.]", "", value.lower())


def stable_index(value: str, modulo: int) -> int:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return int(digest[:12], 16) % modulo


def clean_terms(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        item = str(value).strip()
        if not item:
            continue
        key = normalize_key(item)
        if key and key not in seen:
            seen.add(key)
            result.append(item)
    return result


def is_allowed_name(name: str) -> bool:
    key = normalize_key(name)
    tokens = set(key.split())
    return bool(key) and not bool(tokens.intersection(STOP_SKILL_TERMS))


def description_for(name: str, subcategory: str) -> str:
    text = f"Practical skill for {name.lower()} within {subcategory.lower()} work."
    return " ".join(text.split()[:25])


def category_for_topic(topic: str) -> CategorySpec:
    lowered = topic.lower()
    routing = (
        (("prompt", "agent", "rag", "nlp", "vision", "model", "forecasting", "anomaly"), "AI & Machine Learning"),
        (("data", "metadata", "batch", "streaming"), "Data Engineering"),
        (("database", "query", "schema", "storage"), "Databases"),
        (("security", "threat", "fraud", "privacy", "incident", "auth"), "Cybersecurity"),
        (("network", "telecommunications"), "Networking"),
        (("frontend", "accessibility", "usability", "design system"), "Frontend Development"),
        (("backend", "api", "workflow", "event-driven", "real-time"), "Backend Development"),
        (("mobile",), "Mobile Development"),
        (("embedded", "iot", "firmware", "fpga", "pcb", "vlsi"), "Engineering"),
        (("cad", "thermal", "fluid", "structural", "geotechnical", "hvac", "bim"), "Engineering"),
        (("quality", "lean", "maintenance", "production"), "Manufacturing"),
        (("procurement", "inventory", "transportation", "warehouse", "demand"), "Supply Chain & Logistics"),
        (("clinical", "healthcare", "pharmacovigilance"), "Healthcare"),
        (("bioinformatics", "genomics", "proteomics", "laboratory"), "Biotechnology"),
        (("agronomy", "irrigation", "soil", "crop"), "Agriculture"),
        (("tax", "audit", "budgeting", "valuation", "banking"), "Finance"),
        (("seo", "content", "brand", "campaign", "crm"), "Marketing"),
        (("sales", "customer success", "support"), "Sales"),
        (("recruiting", "learning", "compensation"), "Human Resources"),
        (("contract", "compliance"), "Legal"),
        (("curriculum", "assessment", "instructional"), "Education"),
        (("animation", "video", "audio", "translation", "localization"), "Media & Communication"),
    )
    for needles, category_name in routing:
        if any(needle in lowered for needle in needles):
            return CATEGORY_BY_NAME[category_name]
    return CATEGORY_BY_NAME["Industry Domain Skills"]


CATEGORY_BY_NAME = {category.name: category for category in CATEGORIES}


def build_records() -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    names: set[str] = set()
    aliases: set[str] = set()

    def add(seed: SkillSeed) -> None:
        if len(records) >= TARGET_COUNT or not is_allowed_name(seed.name):
            return
        name_key = normalize_key(seed.name)
        if name_key in names:
            return
        category = CATEGORY_BY_NAME[seed.category]
        raw_aliases = seed.aliases + [compact_alias(seed.name)]
        accepted_aliases: list[str] = []
        for alias in raw_aliases:
            alias_key = normalize_key(alias)
            if not alias_key or alias_key == name_key or alias_key in aliases or alias_key in names:
                continue
            aliases.add(alias_key)
            accepted_aliases.append(alias)
        keywords = clean_terms([seed.name, *accepted_aliases, *seed.keywords, seed.category, seed.subcategory, seed.parent])
        records.append(
            {
                "id": f"SK{len(records) + 1:06d}",
                "name": seed.name,
                "category": seed.category,
                "subcategory": seed.subcategory,
                "parent_skill": seed.parent or category.parent,
                "aliases": clean_terms(accepted_aliases),
                "search_keywords": keywords[:18],
                "related_skills": [],
                "description": seed.description or description_for(seed.name, seed.subcategory),
                "is_soft_skill": bool(seed.soft or category.soft),
                "is_technical": bool(seed.technical or category.technical),
                "popularity_score": max(1, min(100, int(seed.popularity))),
                "status": "active",
            }
        )
        names.add(name_key)

    for seed in (*TECH_SEEDS, *SOFT_SEEDS):
        add(seed)

    for category_name, tools in TOOLS_BY_CATEGORY.items():
        category = CATEGORY_BY_NAME[category_name]
        for tool in tools:
            add(
                SkillSeed(
                    tool,
                    category.name,
                    category.subcategories[0],
                    category.parent,
                    [compact_alias(tool)],
                    [category.parent.lower(), category.name.lower()],
                    description_for(tool, category.subcategories[0]),
                    category.technical,
                    category.soft,
                    78,
                )
            )

    for topic in DOMAIN_TERMS:
        category = category_for_topic(topic)
        for method in METHOD_TERMS:
            if len(records) >= TARGET_COUNT:
                break
            name = f"{topic} {method}"
            subcategory = category.subcategories[stable_index(f"{topic}:{method}", len(category.subcategories))]
            popularity = 58 + stable_index(name, 35)
            add(
                SkillSeed(
                    name,
                    category.name,
                    subcategory,
                    category.parent,
                    [],
                    [topic, method, category.parent],
                    description_for(name, subcategory),
                    category.technical,
                    category.soft,
                    popularity,
                )
            )

    modifiers = (
        "Advanced", "Applied", "Practical", "Enterprise", "Cloud-Native", "Secure", "Scalable", "Automated",
        "Collaborative", "Strategic", "Operational", "Analytical", "Cross-Functional", "Global", "Digital",
    )
    focus_areas = (
        "Workflows", "Platforms", "Systems", "Programs", "Processes", "Operations", "Controls", "Metrics",
        "Roadmaps", "Playbooks", "Pipelines", "Portfolios", "Services", "Products", "Experiences",
    )
    for category in CATEGORIES:
        for subcategory in category.subcategories:
            for topic in DOMAIN_TERMS:
                for modifier in modifiers:
                    if len(records) >= TARGET_COUNT:
                        break
                    focus = focus_areas[stable_index(f"{category.name}:{subcategory}:{topic}:{modifier}", len(focus_areas))]
                    name = f"{modifier} {topic} {focus}"
                    add(
                        SkillSeed(
                            name,
                            category.name,
                            subcategory,
                            category.parent,
                            [],
                            [topic, modifier, focus, subcategory],
                            description_for(name, subcategory),
                            category.technical,
                            category.soft,
                            42 + stable_index(name, 45),
                        )
                    )

    for category in CATEGORIES:
        for subcategory in category.subcategories:
            for topic in DOMAIN_TERMS:
                for method in METHOD_TERMS:
                    if len(records) >= TARGET_COUNT:
                        break
                    name = f"{subcategory} {topic} {method}"
                    add(
                        SkillSeed(
                            name,
                            category.name,
                            subcategory,
                            category.parent,
                            [],
                            [subcategory, topic, method, category.parent],
                            description_for(name, subcategory),
                            category.technical,
                            category.soft,
                            38 + stable_index(name, 48),
                        )
                    )

    if len(records) < TARGET_COUNT:
        raise RuntimeError(f"generated only {len(records)} skills")

    by_category: dict[str, list[str]] = {}
    for record in records:
        by_category.setdefault(str(record["category"]), []).append(str(record["name"]))
    for index, record in enumerate(records):
        pool = by_category[str(record["category"])]
        related = [name for name in pool[index % len(pool) : index % len(pool) + 16] if name != record["name"]]
        if len(related) < 5:
            related.extend([name for name in pool if name != record["name"]][: 5 - len(related)])
        record["related_skills"] = related[:10]

    return records


def validate(records: list[dict[str, object]]) -> dict[str, int]:
    ids = [str(row["id"]) for row in records]
    names = [normalize_key(str(row["name"])) for row in records]
    alias_map: dict[str, str] = {}
    category_names = {category.name for category in CATEGORIES}
    for row in records:
        if row["category"] not in category_names:
            raise ValueError(f"unknown category: {row['category']}")
        if row["status"] != "active":
            raise ValueError(f"invalid status: {row['status']}")
        if len(str(row["description"]).split()) > 25:
            raise ValueError(f"description too long: {row['name']}")
        for alias in row["aliases"]:
            alias_key = normalize_key(str(alias))
            existing = alias_map.get(alias_key)
            if existing and existing != row["name"]:
                raise ValueError(f"alias collision: {alias} -> {existing}, {row['name']}")
            alias_map[alias_key] = str(row["name"])
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate IDs")
    if len(names) != len(set(names)):
        raise ValueError("duplicate names")
    return {"skills": len(records), "aliases": len(alias_map), "categories": len(CATEGORIES)}


def write_exports(records: list[dict[str, object]]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    categories = [
        {
            "name": category.name,
            "subcategories": list(category.subcategories),
            "parent_skill": category.parent,
            "is_technical": category.technical,
            "is_soft_skill": category.soft,
        }
        for category in CATEGORIES
    ]
    alias_rows = [
        {"alias": alias, "skill_id": str(record["id"]), "skill_name": str(record["name"])}
        for record in records
        for alias in record["aliases"]
    ]
    autocomplete = [
        {
            "id": record["id"],
            "name": record["name"],
            "category": record["category"],
            "subcategory": record["subcategory"],
            "aliases": record["aliases"],
            "search_keywords": record["search_keywords"][:10],
        }
        for record in records
    ]

    (OUTPUT_DIR / "skills.json").write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (PUBLIC_DIR / "categories.json").write_text(json.dumps(categories, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUTPUT_DIR / "aliases.json").write_text(json.dumps(alias_rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (PUBLIC_DIR / "skills_autocomplete.json").write_text(json.dumps(autocomplete, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    (OUTPUT_DIR / "skills.txt").write_text("\n".join(str(record["name"]) for record in records) + "\n", encoding="utf-8")

    with (OUTPUT_DIR / "skills.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(records[0].keys()))
        writer.writeheader()
        for record in records:
            row = dict(record)
            for field_name in ("aliases", "search_keywords", "related_skills"):
                row[field_name] = json.dumps(row[field_name], ensure_ascii=False)
            writer.writerow(row)

    with (OUTPUT_DIR / "skills.sql").open("w", encoding="utf-8") as handle:
        handle.write(
            "CREATE TABLE IF NOT EXISTS skills_taxonomy (\n"
            "  id TEXT PRIMARY KEY,\n"
            "  name TEXT UNIQUE NOT NULL,\n"
            "  category TEXT NOT NULL,\n"
            "  subcategory TEXT NOT NULL,\n"
            "  parent_skill TEXT NOT NULL,\n"
            "  aliases JSON NOT NULL,\n"
            "  search_keywords JSON NOT NULL,\n"
            "  related_skills JSON NOT NULL,\n"
            "  description TEXT NOT NULL,\n"
            "  is_soft_skill BOOLEAN NOT NULL,\n"
            "  is_technical BOOLEAN NOT NULL,\n"
            "  popularity_score INTEGER NOT NULL,\n"
            "  status TEXT NOT NULL\n"
            ");\n"
        )
        for record in records:
            values = [
                record["id"],
                record["name"],
                record["category"],
                record["subcategory"],
                record["parent_skill"],
                json.dumps(record["aliases"], ensure_ascii=False),
                json.dumps(record["search_keywords"], ensure_ascii=False),
                json.dumps(record["related_skills"], ensure_ascii=False),
                record["description"],
                "TRUE" if record["is_soft_skill"] else "FALSE",
                "TRUE" if record["is_technical"] else "FALSE",
                str(record["popularity_score"]),
                record["status"],
            ]
            escaped = [f"'{str(value).replace(chr(39), chr(39) + chr(39))}'" for value in values[:8]]
            escaped.append(f"'{str(values[8]).replace(chr(39), chr(39) + chr(39))}'")
            escaped.extend(values[9:12])
            escaped.append(f"'{values[12]}'")
            handle.write(f"INSERT INTO skills_taxonomy VALUES ({', '.join(escaped)});\n")


def main() -> None:
    records = build_records()
    stats = validate(records)
    write_exports(records)
    print(json.dumps(stats, sort_keys=True))


if __name__ == "__main__":
    main()
