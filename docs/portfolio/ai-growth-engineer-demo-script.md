# AI Growth Engineer Demo Script

Target role: AI Growth Engineer / AI Automation / MarTech / Applied AI internship

## Recording Flow

1. Open `http://127.0.0.1:3002`.
2. Show the landing page and explain the product in one sentence.
3. Open `http://127.0.0.1:3002/dashboard`.
4. Point at live recommendations, network activity, InCoScore/profile signals, and production-style navigation.
5. Open `http://127.0.0.1:3002/opportunities` or `http://127.0.0.1:3002/internships-jobs`.
6. Mention the backend proof: `http://127.0.0.1:8000/health` is healthy, with MongoDB, Redis, queue, embeddings, and learned ranker ready.
7. Mention Ask AI proof from the validated prompt:
   "Find AI internships, software engineering jobs, machine learning challenges, and data hackathons I should prioritize."
8. Close by mapping the project to D2C growth automation.

## Natural First-Person Walkthrough Script

Hi, I am Ankan Ghosh, and this is VidyaVerse, an AI-powered opportunity intelligence platform that I built end to end.

I will walk through it like I am using the product normally. The core problem I wanted to solve is that students and early-career candidates usually search across many different platforms for internships, jobs, hackathons, scholarships, workshops, and events. The data is scattered, duplicated, and often not personalized. So I built VidyaVerse to turn that messy opportunity data into a ranked, AI-assisted workflow.

This is the home page. The goal here is to make the product feel like an intelligence layer, not just another listing website. From here, I can go into the dashboard and start seeing the system working.

Now I am opening the dashboard. This is the main product view. On the left, I have navigation for opportunities, internships and jobs, applications, social features, leaderboard, experiments, and other product areas. In the center, the dashboard shows live recommendations. These are not hardcoded cards. They come from the backend and are scored using opportunity data, ranking logic, embeddings, and profile signals.

Here I also have product components like profile strength, active applications, network activity, and InCoScore. I designed this so a user can keep coming back and immediately understand what to do next: what to apply to, what to improve, and where they stand.

Next, I will show the opportunities area. This is where the user can browse listings and move toward action. Behind the scenes, the backend is built with FastAPI, MongoDB, Redis, background jobs, and a ranking pipeline. I also use embeddings and vector search, so the system can understand semantic meaning instead of only matching exact keywords.

The AI layer is one of the most important parts. I built an Ask AI flow where the user can ask a natural-language question like, "Find AI internships, software engineering jobs, machine learning challenges, and data hackathons I should prioritize." The system first retrieves relevant opportunities, then sends only that grounded context to the LLM, and then returns structured results with top matches, citations, recommended actions, and hallucination checks.

So the AI is not just generating generic text. It is connected to real data, retrieval, scoring, and safety checks. In my validation run, it retrieved five relevant results, selected three top opportunities, attached citations, and passed the hallucination checks.

On the engineering side, I treated this like a production system. I have a backend health endpoint that checks MongoDB, Redis, the queue, embeddings, and the learned ranker. I also added protected authentication, Turnstile-based login protection, background workers, observability hooks, model readiness checks, and fallback behavior if an AI provider fails.

The same architecture can be applied beyond opportunities. For example, the input data could be customer segments, campaign performance, product reviews, support messages, ad creatives, or retention data. Then an AI workflow can score users, suggest actions, generate grounded content, automate follow-ups, and track which campaigns actually perform better.

That is what I wanted to show through this project: I can build the full system, not only a small AI wrapper. I can connect APIs, databases, background jobs, ranking models, LLMs, analytics, and frontend workflows into something that actually works end to end.

So VidyaVerse is my way of demonstrating how I think as a software engineer and AI automation engineer: start with a real workflow, use data properly, add AI where it creates leverage, and build a reliable product experience around it.

## Optional Closing Line

If I joined Village Company, I would apply this same approach to AI-powered content workflows, customer segmentation, campaign analysis, retention automation, and founder-facing dashboards that help a small team move faster.
