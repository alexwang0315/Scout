import asyncio

# Global queue for PDR events to be processed by AI worker
pdr_event_queue: asyncio.Queue = asyncio.Queue(maxsize=1000)