import json
from langchain_openai import ChatOpenAI

# -------------------
# 1. Initialize OpenAI LLM
# -------------------
llm = ChatOpenAI(
    model="gpt-4o-mini",  # or "gpt-4o" / "gpt-3.5-turbo"
    temperature=0
)

# -------------------
# 2. Function to query OpenAI directly
# -------------------
def run_agent1(query: str, product_json: dict | list) -> str:
    """
    Sends the query and product JSON directly to the OpenAI LLM.
    """
    prompt = f"Here is the product JSON: {json.dumps(product_json)}\n\n{query}"
    response = llm.chat([{"role": "user", "content": prompt}])
    return response.content  # directly get the text