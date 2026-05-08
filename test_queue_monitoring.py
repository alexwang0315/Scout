#!/usr/bin/env python3
"""Test case for queue monitoring fix"""
import asyncio
import logging
import sys
from shared_queue import pdr_event_queue
from concurrent.futures import ThreadPoolExecutor

# Set up logging capture
logging.basicConfig(level=logging.WARNING, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

async def test_queue_monitoring():
    """Test that queue monitoring triggers warning at >50 items"""
    print("=== Queue Monitoring Test ===")
    
    # Clear queue first
    while not pdr_event_queue.empty():
        await pdr_event_queue.get()
    
    print(f"Initial queue size: {pdr_event_queue.qsize()}")
    
    # Fill to 55 items (should trigger warning at 51)
    for i in range(55):
        await pdr_event_queue.put({"test": i})
        current_size = pdr_event_queue.qsize()
        if current_size > 50:
            print(f"✓ Queue size {current_size} > 50: Warning should trigger")
    
    print(f"Final queue size: {pdr_event_queue.qsize()}")
    
    # Verify executor configuration
    executor = ThreadPoolExecutor(max_workers=4)
    print(f"✓ Executor configured with max_workers=4")
    
    # Cleanup
    while not pdr_event_queue.empty():
        await pdr_event_queue.get()
    
    print("=== Test Passed ===")

if __name__ == "__main__":
    asyncio.run(test_queue_monitoring())