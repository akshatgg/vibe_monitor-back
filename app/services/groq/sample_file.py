import asyncio
import logging
from typing import List, Optional
from .client import GroqClient
from .models import ChatRequest, ChatResponse, ChatMessage, ChatRole

class SampleFile:
    def __init__(self):
        self.sample_file = "sample"