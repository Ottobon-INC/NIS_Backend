import asyncio
from app.db.session import engine, AsyncSessionLocal
from app.db.base import Base
from app.models.company_knowledge import CompanyProfile, Service, Product, Capability, UseCase, CaseStudy

async def seed():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    async with AsyncSessionLocal() as session:
        # Check if already present
        from sqlalchemy import select
        existing = (await session.execute(select(Service))).scalars().all()
        if existing:
            print("Services already exist:", len(existing))
            return

        profile = CompanyProfile(
            id="prof-ottobon",
            name="Ottobon (NetworkOS)",
            description="Ottobon delivers high-velocity enterprise software modernization, automated data pipelines, API integrations, and relationship intelligence operating systems."
        )
        session.add(profile)

        services = [
            Service(
                id="svc-reporting",
                name="Automated Reporting & Data Pipelines",
                description="End-to-end automated report generation, data extraction, and scalable export pipeline designed to handle rapid client growth and high-volume business metrics."
            ),
            Service(
                id="svc-cloud",
                name="Cloud Modernization & Architecture Refactoring",
                description="High-throughput cloud architecture refactor, containerization, and database optimization providing low latency SLA and monolith deconstruction."
            ),
            Service(
                id="svc-integration",
                name="API & Multi-System Integration",
                description="Enterprise integration platform connecting fragmented CRM, ERP, and internal software with bidirectional real-time data synchronization and webhooks."
            ),
            Service(
                id="svc-soc2",
                name="SOC2 Compliance & Security Governance",
                description="Audit control implementation, encryption at rest and in transit, and security governance frameworks for SOC2 Type II compliance."
            )
        ]
        for s in services:
            session.add(s)

        products = [
            Product(
                id="prod-networkos",
                name="NetworkOS Platform",
                description="Commercial relationship intelligence and workflow orchestration operating system."
            )
        ]
        for p in products:
            session.add(p)

        capabilities = [
            Capability(
                id="cap-reporting",
                name="Automated Reporting & Data Pipelines",
                description="Automated scheduled data aggregation, transformation, and export pipelines to eliminate manual reporting overhead."
            ),
            Capability(
                id="cap-cloud",
                name="Cloud Modernization & Architecture Refactoring",
                description="Microservices refactoring, containerization, and database optimization for scalable low-latency performance."
            ),
            Capability(
                id="cap-integration",
                name="Enterprise API & Multi-System Integration",
                description="Connecting fragmented enterprise applications (CRM, ERP, clinic/billing portals) with bidirectional real-time API synchronization."
            ),
            Capability(
                id="cap-soc2",
                name="SOC2 Compliance & Security Governance",
                description="Implementation of audit logging, RBAC, encryption at rest/in transit, and security governance frameworks."
            ),
            Capability(
                id="cap-ai-rag",
                name="Enterprise AI Orchestration & RAG Systems",
                description="Architecting grounded retrieval-augmented generation (RAG) and hybrid intent-routing language model microservices."
            )
        ]
        for c in capabilities:
            session.add(c)

        use_cases = [
            UseCase(
                id="uc-reporting",
                name="Automated Client Reporting Pipeline",
                description="Eliminates weekly manual report compilation for high-growth SaaS firms by establishing real-time data synchronization and automated PDF/CSV distribution."
            ),
            UseCase(
                id="uc-cloud",
                name="High-Traffic Monolith Architecture Modernization",
                description="Refactors legacy backend services into decoupled high-throughput asynchronous microservices to achieve sub-100ms API response times."
            )
        ]
        for u in use_cases:
            session.add(u)

        case_studies = [
            CaseStudy(
                id="cs-cloud-latency",
                title="E-Commerce Architecture Refactoring & Latency Reduction",
                content="Modernized core order ingestion microservice reducing checkout latency by 65% and eliminating database lock contention during flash sales."
            ),
            CaseStudy(
                id="cs-reporting-ops",
                title="Financial Services Automated Reporting Transformation",
                content="Replaced 20+ hours per week of manual financial report generation with an automated scheduled aggregation and export pipeline."
            )
        ]
        for cs in case_studies:
            session.add(cs)

        await session.commit()
        print("Database initialized and seeded successfully!")

if __name__ == "__main__":
    asyncio.run(seed())
