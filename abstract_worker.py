from __future__ import annotations
from abc import ABC, abstractmethod
from pydantic import BaseModel

class ReturnData(BaseModel):
    service: str
    query: str
    total_records: int
    records: list[dict]

class ReturnError(BaseModel): 
    service: str
    query: str
    error_code: int
    error_message: str

class AbstractWorker(ABC): 
    """Abstract base class to ensure worker classes are properly implemented
    See https://www.geeksforgeeks.org/factory-method-python-design-patterns/"""

    def __init__(self): 
        pass

    @abstractmethod
    async def get(self): 
        raise NotImplementedError
    
    @abstractmethod
    async def normalize_rv(data): 
        pass
