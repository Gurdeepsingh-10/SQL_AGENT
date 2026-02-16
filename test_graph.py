import asyncio
from app.core.agent.graph import graph
from app.core.agent.state import AgentState

async def test_graph():
    inputs = {
        "query": "hello",
        "schema_context": "",
        "db_connection_id": 1
    }
    config = {"configurable": {"thread_id": "test_thread_1"}}
    
    print(f"Invoking graph with config: {config}")
    try:
        result = await graph.ainvoke(inputs, config=config)
        print("Success!")
        print(result)
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_graph())
