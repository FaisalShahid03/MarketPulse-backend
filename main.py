import sys
import asyncio

if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())


from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import json
from typing import List
from agent2 import scrape_products
from agent1 import run_agent
from agent4 import run_agent1

app = FastAPI()

class ScrapeRequest(BaseModel):
    url: str

# -----------------------------
# Agent 2 endpoint
# -----------------------------

@app.post("/scrape")
async def scrape_endpoint(request: ScrapeRequest):
    print(request)
    products = await scrape_products(request.url)
    return {"products": products}

class CompanyQuery(BaseModel):
    company_query: str

# -----------------------------
# Agent 1 endpoint
# -----------------------------
@app.post("/competitors")
async def competitors_endpoint(request: CompanyQuery):
    company_query = request.company_query.strip()
    if not company_query:
        raise HTTPException(status_code=400, detail="company_query cannot be empty")

    try:
        result = await run_agent(company_query)
        return {"company_query": company_query, "competitors_json": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Agent execution failed: {e}")



class QueryRequest(BaseModel):
    query: str
    product_json: dict | list

@app.post("/ask")
async def ask(request: QueryRequest):
    answer = run_agent1(request.query, request.product_json)
    return {"answer": answer}
