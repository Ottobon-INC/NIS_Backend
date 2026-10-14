import sys
sys.path.insert(0, r'c:\Users\poorv\OneDrive\Desktop\NetworkOS\NIS_Backend')
import asyncio
import json
from app.db.session import AsyncSessionLocal
from sqlalchemy import text

products = [
    {
        "id": "prod-janmasethu",
        "name": "JanmaSethu",
        "tagline": "Bridge to Parenthood — Journey-Aware Healthtech Platform",
        "category": "Healthtech & Maternity",
        "description": "A highly dynamic, ecosystem-driven healthtech platform designed to guide couples through the entire parenthood journey—from deciding to conceive (TTC) to fertility treatments, pregnancy, and early parenting. Combines clinician-reviewed knowledge, peer community, hybrid AI emotional companion (Sakhi), bilingual Telugu/English support, and an independent B2B clinic portal.",
        "features": json.dumps([
            "Journey-Aware Architecture (Adaptive UI for TTC, Pregnancy, and Parenting)",
            "Sakhi AI Chat Companion (Hybrid AI omnichannel emotional support on Web & WhatsApp)",
            "Bilingual Experience (Native English and Telugu regional-first interface)",
            "9+ Specialized Health Calculators & Checklists (Fertility window, gestational trackers, newborn milestones)",
            "Clinician-Reviewed Knowledge Hub & Peer Community",
            "Standalone B2B Clinic Portal with Patient Preparedness Scoring & Inbound Lead Management"
        ]),
        "target_audience": "Couples planning pregnancy, TTC/IVF patients, new parents, and fertility clinics/hospitals",
        "business_model": "B2C Premium Subscriptions & B2B Clinic Lead Ingestion SaaS",
        "status": "ACTIVE"
    },
    {
        "id": "prod-ottobon-courses",
        "name": "Ottobon Course Platform",
        "tagline": "Don't just watch. Build. Structured AI-native learning for practical upskilling",
        "category": "AI-Native EdTech",
        "description": "A structured, AI-native guided upskilling environment inside the Ottobon Academy ecosystem that transitions learners from passive content consumption to building practical capability. Built on the core framework: Learn -> Comprehend -> Articulate -> Apply, with AI doubt clarification, checkpoints, and real-world project sandboxes.",
        "features": json.dumps([
            "4-Stage Learning Framework (Learn/Listen -> Comprehend -> Articulate -> Apply)",
            "AI-Assisted Doubt Clarification & Intelligent Interactive Tutor",
            "Automated Assessment Checkpoints & Code Validation Sandboxes",
            "Hands-on Project & Capstone Building Workspaces",
            "Cohort Engagement, Peer Collaboration & Learning Streaks",
            "Adaptive Progress Visibility & Skill Mastery Verification"
        ]),
        "target_audience": "Software developers, engineering students, career switchers, and technical professionals",
        "business_model": "Cohort Tuition, Self-Paced Course Licenses, and Enterprise Academy Tracks",
        "status": "ACTIVE"
    },
    {
        "id": "prod-sbloom",
        "name": "sBLOOM",
        "tagline": "Bloom Your Social Footprint — Creator, Content & Digital-Growth Ecosystem",
        "category": "Creator Economy & Media Infrastructure",
        "description": "A comprehensive creator, content, and digital-growth ecosystem under Autobahn Professional Services combining physical studio infrastructure (sBLOOM Cre@tors Studio) with an end-to-end digital content engine (Idea -> Plan -> Create -> Edit -> Enhance -> Distribute -> Discover -> Grow) for creators, professionals, and enterprises.",
        "features": json.dumps([
            "Physical sBLOOM Cre@tors Studio (Podcast sets, reels studios, 4K cameras, editing suites)",
            "8-Stage Content Production Engine (Idea to Distribution & Growth)",
            "Cross-Platform Social Footprint Expansion (Social video, SEO authority, thought leadership)",
            "AI-Assisted Content Repurposing (Transcripts to short-form video hooks & articles)",
            "Creator-to-Business Matching & Sponsorship Marketplace",
            "Managed Content Subscriptions for Executives & Institutions"
        ]),
        "target_audience": "Digital creators & influencers, business founders & executives, and institutions/enterprises",
        "business_model": "Studio Memberships, Managed Production Packages, and Content Retainers",
        "status": "ACTIVE"
    },
    {
        "id": "prod-talentops",
        "name": "TalentOps",
        "tagline": "AI-Powered Workforce Operations Platform",
        "category": "HR Tech & Workforce Operations",
        "description": "An AI-powered Managed Workforce Operations Platform transforming traditional HR management into a highly automated, intelligence-driven service model. Operates on a Human-in-the-Loop model where AI executes routine operations, human operators supervise exceptions, and domain experts handle escalations, reducing HR overhead by over 80%.",
        "features": json.dumps([
            "Human-in-the-Loop AI Operating Model (AI Automation + Human Oversight + Expert Escalation)",
            "80%+ Reduction in Operational HR Workload",
            "Automated Employee Onboarding & Lifecycle Records Management",
            "Intelligent Task & Attendance Tracking with Automated Leave Validation",
            "Automated Payroll Preparation & Regulatory Compliance Auditing",
            "24/7 AI Virtual HR Assistant for Employee Queries & Policy Guidance",
            "Executive Operations Dashboard with Real-time Workforce Productivity Analytics"
        ]),
        "target_audience": "High-growth startups, SMEs, and distributed enterprise organizations",
        "business_model": "Managed Workforce Operations Service (MWOS) Monthly Subscription",
        "status": "ACTIVE"
    },
    {
        "id": "prod-networkos",
        "name": "NetworkOS Platform",
        "tagline": "Commercial Relationship Intelligence Operating System",
        "category": "Enterprise Relationship OS",
        "description": "The foundational operating system for high-trust commercial relationship intelligence, autonomous multi-source research orchestration, evidence-based problem matching, and founder decision workflows.",
        "features": json.dumps([
            "Autonomous Multi-Source Research Orchestration",
            "Executive 360 Contact Intelligence & Verified Dossiers",
            "Evidence-Based Problem & Capability Matching Engine",
            "Founder Decision Queue & Relationship Capital Pipeline"
        ]),
        "target_audience": "Founders, Managing Partners, Enterprise Business Development Leaders",
        "business_model": "Enterprise Platform Subscription & Intelligence Tier",
        "status": "ACTIVE"
    }
]

async def main():
    async with AsyncSessionLocal() as db:
        print("Upserting products into database...")
        for p in products:
            stmt = text("""
                INSERT INTO products (id, name, tagline, category, description, features, target_audience, business_model, status, created_at, updated_at)
                VALUES (:id, :name, :tagline, :category, :description, :features, :target_audience, :business_model, :status, now(), now())
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name,
                    tagline = EXCLUDED.tagline,
                    category = EXCLUDED.category,
                    description = EXCLUDED.description,
                    features = EXCLUDED.features,
                    target_audience = EXCLUDED.target_audience,
                    business_model = EXCLUDED.business_model,
                    status = EXCLUDED.status,
                    updated_at = now();
            """)
            await db.execute(stmt, p)
        await db.commit()
        print(f"Successfully seeded {len(products)} products into the database!")

asyncio.run(main())
