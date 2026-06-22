import asyncio
from sqlalchemy import select
from models.database import PipelineRunORM, DiscoveredDocumentORM, ClassifiedDocumentORM, async_session_factory

async def main():
    async with async_session_factory() as session:
        # Check runs
        runs = (await session.execute(select(PipelineRunORM))).scalars().all()
        print("--- Pipeline Runs ---")
        for r in runs:
            print(f"Run ID: {r.id}, Status: {r.status}, Discovered: {r.documents_discovered}, Novel: {r.documents_novel}, Classified: {r.documents_classified}, Quarantined: {r.documents_quarantined}, Errors: {r.errors}")
            
        # Check docs
        docs = (await session.execute(select(DiscoveredDocumentORM))).scalars().all()
        print("\n--- Discovered Documents ---")
        for d in docs:
            print(f"Doc ID: {d.id}, Status: {d.status}, URL: {d.url[:80]}, Error: {d.last_error}")
            
        # Check classifications
        classifications = (await session.execute(select(ClassifiedDocumentORM))).scalars().all()
        print("\n--- Classifications ---")
        for c in classifications:
            print(f"Class ID: {c.id}, Doc ID: {c.document_id}, AMC: {c.amc_name}, Scheme: {c.scheme_name}, Confidence: {c.confidence_score}, Quarantined: {c.is_quarantined}, Reason: {c.quarantine_reason}")

if __name__ == "__main__":
    asyncio.run(main())
