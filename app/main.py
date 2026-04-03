from fastapi import FastAPI
from app.chains.rag import query_rag

app = FastAPI()


@app.get("/")
async def root():
    return {
        "name": "compose_langchain",
        "status": "ok",
        "docs": "/docs",
        "endpoints": ["POST /rag/query"],
    }


@app.get("/health")
async def health_check():
    return {"status": "healthy"}

@app.post("/rag/query")
async def rag_query(payload: dict):
    return await query_rag(payload["query"])


# TODO: Add your real router and graph/oracle endpoints
# from app.services.oracle import router as oracle_router
# app.include_router(oracle_router, prefix="/oracle")

