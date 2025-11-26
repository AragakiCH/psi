import asyncio
import json
import logging
from fastapi import WebSocket, WebSocketDisconnect

from .buffer import data_buffer

log = logging.getLogger("ctrlx.ws")

async def websocket_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    log.info("WS connection open")
    last_seq = None
    try:
        while True:
            batch = data_buffer.after(last_seq)
            if batch:
                for snap in batch:
                    await websocket.send_text(json.dumps(snap))
                last_seq = batch[-1]["__seq__"]
            await asyncio.sleep(0.02)  # ~50 Hz
    except WebSocketDisconnect:
        log.info("WS connection closed")
