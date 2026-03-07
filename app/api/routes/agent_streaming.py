from fastapi import APIRouter
from fastapi.responses import StreamingResponse
import json
import time
from app.schemas.agent import AgentQueryRequest
from app.core.agent.graph import graph # assuming this import based on usage

router = APIRouter()

@router.post("/agent/query-stream")
async def query_stream(request: AgentQueryRequest):
    """Stream agent steps in real-time using Server-Sent Events."""
    async def event_generator():
        try:
            # Stream graph steps instead of waiting for completion
            thread_id = request.connection_id or "default"
            async for event in graph.astream_events(
                inputs={"query": request.query, "connection_id": request.connection_id},
                config={"configurable": {"thread_id": thread_id}},
                version="v2"
            ):
                # Each node completion triggers a stream event
                if event["event"] == "on_chain_end":
                    node_name = event["name"]
                    data = event["data"].get("output", {})
                    
                    # Emit JSON over SSE
                    yield f"data: {json.dumps({'node': node_name, 'data': data, 'timestamp': time.time()})}\n\n"
                    
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream"
    )
