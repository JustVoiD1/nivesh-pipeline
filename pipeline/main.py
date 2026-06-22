"""FastAPI Main Application.

Exposes endpoints to trigger pipeline runs, view quarantine queues, 
and manage sources for the Next.js Dashboard.
"""
import uuid
from typing import Any, AsyncGenerator
from dotenv import load_dotenv
from pathlib import Path
load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")

import sys
import asyncio

if sys.platform == "win32":
    try:
        policy = asyncio.WindowsProactorEventLoopPolicy()
        asyncio.set_event_loop_policy(policy)
        
        import uvicorn.config
        def patched_setup(self):
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        uvicorn.config.Config.setup_event_loop = patched_setup
    except Exception:
        pass

from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from config.loader import load_sources
from models.database import (
    ClassifiedDocumentORM, DiscoveredDocumentORM, PipelineRunORM, 
    SourceConfigORM, get_db_session, init_db
)
from models.schemas import (
    HealthResponse, PipelineRunRequest, ReviewRequest, StatsResponse
)
from observability.logger import setup_logging, get_logger
from orchestrator import PipelineOrchestrator

setup_logging("INFO")
logger = get_logger(__name__)

app = FastAPI(title="Nivesh AI AMC Pipeline API", version="1.0.0")

# Allow dashboard to connect
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

import asyncio

# Global dictionary to track running tasks by source_key
active_tasks: dict[str, asyncio.Task] = {}

@app.on_event("startup")
async def startup_event():
    await init_db()
    
    # Mark any dangling RUNNING runs as FAILED on startup
    from models.database import async_session_factory, PipelineRunORM
    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(
                update(PipelineRunORM)
                .where(PipelineRunORM.status == "RUNNING")
                .values(
                    status="FAILED",
                    errors="Dangling run cleaned up on system startup."
                )
            )
    
    # Sync sources from YAML to DB on startup
    sources_yaml = load_sources()
    async with async_session_factory() as session:
        async with session.begin():
            for s in sources_yaml:
                result = await session.execute(
                    select(SourceConfigORM).where(SourceConfigORM.source_key == s["source_key"])
                )
                existing = result.scalar_one_or_none()
                if not existing:
                    new_source = SourceConfigORM(
                        source_key=s["source_key"],
                        amc_name=s["amc_name"],
                        base_url=s["base_url"],
                        page_type=s.get("page_type", "JS_SPA"),
                        discovery_strategy=s.get("discovery", {}).get("strategy", "link_extraction"),
                        selectors=s.get("discovery", {}),
                        anti_bot_config=s.get("anti_bot", {}),
                        file_types=s.get("file_types", ["xlsx", "pdf"])
                    )
                    session.add(new_source)


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    return HealthResponse()


@app.get("/sources")
async def get_sources(session: AsyncSession = Depends(get_db_session)):
    """List all configured AMC sources with running status."""
    result = await session.execute(select(SourceConfigORM))
    sources = result.scalars().all()
    
    # Get active runs
    active_runs_res = await session.execute(
        select(PipelineRunORM.source_id)
        .where(PipelineRunORM.status == "RUNNING")
    )
    active_source_ids = set(active_runs_res.scalars().all())
    
    items = []
    for src in sources:
        items.append({
            "id": str(src.id),
            "source_key": src.source_key,
            "amc_name": src.amc_name,
            "base_url": src.base_url,
            "page_type": src.page_type,
            "discovery_strategy": src.discovery_strategy,
            "file_types": src.file_types,
            "enabled": src.enabled,
            "is_running": src.id in active_source_ids
        })
    return items


@app.post("/pipeline/run/{source_key}")
async def trigger_pipeline(
    source_key: str, 
    request: PipelineRunRequest,
    session: AsyncSession = Depends(get_db_session)
):
    """Trigger a pipeline run for a specific source."""
    if source_key in active_tasks:
        raise HTTPException(status_code=400, detail="Pipeline is already running for this source")

    result = await session.execute(
        select(SourceConfigORM).where(SourceConfigORM.source_key == source_key)
    )
    source = result.scalar_one_or_none()
    
    if not source:
        raise HTTPException(status_code=404, detail=f"Source {source_key} not found")

    run_id = uuid.uuid4()
    
    # Create and commit the run record immediately so that the status is instantly visible to other API endpoints
    from models.database import PipelineRunORM
    run_record = PipelineRunORM(
        id=run_id,
        source_id=source.id,
        status="RUNNING"
    )
    session.add(run_record)
    await session.commit()
    
    # Run in background to avoid blocking the API
    async def _run_pipeline_bg(s_id, r_id, force_ref):
        try:
            async for bg_session in get_db_session():
                res = await bg_session.execute(select(SourceConfigORM).where(SourceConfigORM.id == s_id))
                s_orm = res.scalar_one_or_none()
                if s_orm:
                    config_dict = {
                        "id": s_orm.id,
                        "source_key": s_orm.source_key,
                        "amc_name": s_orm.amc_name,
                        "base_url": s_orm.base_url,
                        "file_types": s_orm.file_types,
                        "anti_bot": s_orm.anti_bot_config,
                        "discovery": s_orm.selectors
                    }
                    orchestrator = PipelineOrchestrator(bg_session)
                    await orchestrator.run_pipeline(config_dict, r_id, force_ref)
                break
        except asyncio.CancelledError:
            logger.info("pipeline_run_cancelled", source_key=source_key, run_id=str(r_id))
            # Mark the run as FAILED in the DB
            from models.database import async_session_factory, PipelineRunORM
            async with async_session_factory() as db_session:
                async with db_session.begin():
                    await db_session.execute(
                        update(PipelineRunORM)
                        .where(PipelineRunORM.id == r_id)
                        .values(status="FAILED", errors="Cancelled by user")
                    )
            raise
        except Exception as e:
            logger.exception("pipeline_run_failed_bg", error=str(e))
        finally:
            active_tasks.pop(source_key, None)

    task = asyncio.create_task(_run_pipeline_bg(source.id, run_id, request.force_refresh))
    active_tasks[source_key] = task
    
    return {"message": "Pipeline started", "run_id": str(run_id)}


@app.post("/pipeline/stop/{source_key}")
async def stop_pipeline(
    source_key: str,
    session: AsyncSession = Depends(get_db_session)
):
    """Stop a running pipeline for a specific source."""
    result = await session.execute(
        select(SourceConfigORM).where(SourceConfigORM.source_key == source_key)
    )
    source = result.scalar_one_or_none()
    if not source:
        raise HTTPException(status_code=404, detail=f"Source {source_key} not found")
        
    task = active_tasks.get(source_key)
    task_cancelled = False
    if task and not task.done():
        task.cancel()
        task_cancelled = True
        
    # Also update DB status to make sure active runs are marked as FAILED/STOPPED
    from models.database import PipelineRunORM
    await session.execute(
        update(PipelineRunORM)
        .where(PipelineRunORM.source_id == source.id)
        .where(PipelineRunORM.status == "RUNNING")
        .values(status="FAILED", errors="Stopped by user request")
    )
    await session.commit()
    
    return {
        "message": "Pipeline stop requested", 
        "source_key": source_key,
        "task_cancelled": task_cancelled
    }


@app.get("/quarantine")
async def get_quarantine_queue(
    limit: int = 100,
    offset: int = 0,
    session: AsyncSession = Depends(get_db_session)
):
    """Get documents pending manual review in quarantine."""
    result = await session.execute(
        select(ClassifiedDocumentORM, DiscoveredDocumentORM)
        .join(DiscoveredDocumentORM, ClassifiedDocumentORM.document_id == DiscoveredDocumentORM.id)
        .where(ClassifiedDocumentORM.is_quarantined == True)
        .where(ClassifiedDocumentORM.review_decision == None)
        .limit(limit)
        .offset(offset)
    )
    
    items = []
    for cls_doc, disc_doc in result.all():
        items.append({
            "classification_id": str(cls_doc.id),
            "document_id": str(disc_doc.id),
            "url": disc_doc.url,
            "filename": disc_doc.filename,
            "amc_name": cls_doc.amc_name,
            "scheme_name": cls_doc.scheme_name,
            "period_label": cls_doc.period_label,
            "confidence_score": cls_doc.confidence_score,
            "quarantine_reason": cls_doc.quarantine_reason,
            "quarantine_details": cls_doc.quarantine_details,
            "signals": cls_doc.classification_signals
        })
    return items


@app.post("/quarantine/{classification_id}/review")
async def review_quarantined_document(
    classification_id: uuid.UUID,
    review: ReviewRequest,
    session: AsyncSession = Depends(get_db_session)
):
    """Submit a manual review decision for a quarantined document."""
    result = await session.execute(
        select(ClassifiedDocumentORM).where(ClassifiedDocumentORM.id == classification_id)
    )
    doc = result.scalar_one_or_none()
    
    if not doc:
        raise HTTPException(status_code=404, detail="Classification record not found")
        
    doc.review_decision = review.decision.value
    doc.reviewed_by = review.reviewer
    doc.review_notes = review.notes
    import datetime
    doc.reviewed_at = datetime.datetime.utcnow()
    
    # Set quarantined to false for any resolved decision (accepted, reclassified, or rejected)
    doc.is_quarantined = False
    
    if review.decision.value in ("ACCEPTED", "RECLASSIFIED"):
        if review.corrected_amc_name: doc.amc_name = review.corrected_amc_name
        if review.corrected_scheme_name: doc.scheme_name = review.corrected_scheme_name
        if review.corrected_period_month: doc.period_month = review.corrected_period_month
        if review.corrected_period_year: doc.period_year = review.corrected_period_year
        
        # In a real app, we would now trigger extraction & loading for this document
        
    await session.commit()
    return {"status": "success", "message": "Review recorded"}


@app.get("/documents")
async def get_discovered_documents(
    limit: int = 100,
    offset: int = 0,
    session: AsyncSession = Depends(get_db_session)
):
    """List all discovered documents with pagination."""
    result = await session.execute(
        select(DiscoveredDocumentORM, SourceConfigORM.amc_name)
        .join(SourceConfigORM, DiscoveredDocumentORM.source_id == SourceConfigORM.id)
        .order_by(DiscoveredDocumentORM.discovered_at.desc())
        .limit(limit)
        .offset(offset)
    )
    items = []
    for doc, amc_name in result.all():
        items.append({
            "id": str(doc.id),
            "url": doc.url,
            "filename": doc.filename,
            "file_type": doc.file_type,
            "file_size_bytes": doc.file_size_bytes,
            "status": doc.status,
            "is_novel": doc.is_novel,
            "discovered_at": doc.discovered_at,
            "amc_name": amc_name
        })
    return items


@app.get("/stats", response_model=StatsResponse)
async def get_stats(session: AsyncSession = Depends(get_db_session)):
    """Get high-level pipeline statistics for the dashboard."""
    from sqlalchemy import func
    from models.database import PublishedDataORM
    
    # Example queries - would need error handling in production
    total_srcs = (await session.execute(select(func.count(SourceConfigORM.id)))).scalar() or 0
    enabled_srcs = (await session.execute(select(func.count(SourceConfigORM.id)).where(SourceConfigORM.enabled == True))).scalar() or 0
    total_docs = (await session.execute(select(func.count(DiscoveredDocumentORM.id)))).scalar() or 0
    quarantine = (await session.execute(select(func.count(ClassifiedDocumentORM.id)).where(ClassifiedDocumentORM.is_quarantined == True))).scalar() or 0
    published = (await session.execute(select(func.count(PublishedDataORM.id)))).scalar() or 0
    
    return StatsResponse(
        total_sources=total_srcs,
        enabled_sources=enabled_srcs,
        total_documents=total_docs,
        total_quarantined=quarantine,
        total_published=published,
        recent_runs=0,
        active_drift_alerts=0
    )

@app.get("/published")
async def get_published_data(
    amc_name: str = None, 
    scheme_name: str = None, 
    limit: int = 100, 
    offset: int = 0,
    session: AsyncSession = Depends(get_db_session)
):
    """Get published portfolio holdings records from the warehouse."""
    from models.database import PublishedDataORM
    query = select(PublishedDataORM)
    if amc_name:
        query = query.where(PublishedDataORM.amc_name == amc_name)
    if scheme_name:
        query = query.where(PublishedDataORM.scheme_name.ilike(f"%{scheme_name}%"))
    
    query = query.order_by(PublishedDataORM.pct_to_net_assets.desc().nulls_last(), PublishedDataORM.market_value.desc().nulls_last()).limit(limit).offset(offset)
    result = await session.execute(query)
    return result.scalars().all()



if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
