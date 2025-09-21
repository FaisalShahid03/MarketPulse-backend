# Requirements (install once in your env):
# pip install -U langchain langchain-community langchain-google-genai duckduckgo-search
# And set your key:
from langchain.agents import initialize_agent, AgentType
from langchain.agents import AgentExecutor
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_community.tools import DuckDuckGoSearchResults

def build_competitor_agent(model: str = "gemini-1.5-flash") -> AgentExecutor:
    """
    Agent that:
      - Uses DuckDuckGo web search to research competitors
      - Returns STRICT JSON (as a string)
    Uses CHAT_ZERO_SHOT_REACT_DESCRIPTION to avoid custom prompt/scratchpad pitfalls.
    """
    llm = ChatGoogleGenerativeAI(model=model, temperature=0)
    web_search = DuckDuckGoSearchResults(
        name="web_search",
        max_results=12,
        description="Search the web via DuckDuckGo and return result snippets with links."
    )
    tools = [web_search]

    agent = initialize_agent(
        tools=tools,
        llm=llm,
        agent=AgentType.CHAT_ZERO_SHOT_REACT_DESCRIPTION,
        verbose=False,
        handle_parsing_errors=True,
    )
    return agent

async def run_agent(company_query: str, model: str = "gemini-1.5-flash") -> str:
    """
    Build and invoke the agent. Returns the agent's RAW JSON string (per instructions).
    """
    agent = build_competitor_agent(model=model)

    instructions = f"""
You are a competitive intelligence analyst.

Task: Given a company, find DIRECT competitors (same product/service category, similar buyers).
Use the `web_search` tool to research.
Prioritize official company sites, recent roundups, analyst pages, and trusted tech media.
Exclude job boards, generic directories, unrelated products, resellers, and partners.
If adjacent (e.g., MSP vs MDR, SIEM vs SOAR), include only if it markets a directly competing offer.
Cross-check brand ↔ domain consistency.

Return STRICT JSON ONLY in this schema:
{{
  "company": "<input company>",
  "competitors": [
    {{
      "name": "string",
      "domain": "string",
      "why_competitor": "1-2 line justification tied to offering & buyers",
      "category": "short label (e.g., SOAR, XDR, MDR, AI-native SOC)",
      "sources": ["https://...", "https://..."]
    }}
  ],
  "confidence": 0.0
}}

Rules:
- 5–12 competitors unless niche makes fewer likely.
- Provide 1–2 credible sources per item.
- confidence in [0,1].
- Output must be valid JSON; do not add commentary.

Now, find direct competitors for: {company_query}
Make sure they are valid, and return atleast 5-10 competitors
"""

    # ainvoke returns a dict with "output"
    result = await agent.ainvoke({"input": instructions})
    return result["output"]

# --- Notebook usage with `await` ---
# Example:
# company_query = "Outfitters"
# out = await run_agent(company_query)
# print(out)
