from __future__ import annotations
from abc import ABC, abstractmethod
import json 


class ReturnData(): 
    def __init__(self, query: str, total_records: int, records: list = []): 
        self.query = query
        self.total_records = total_records
        self.records = records
    
    def to_json(self): 
        return json.dump({
            'query': self.query, 
            'total_records': self.total_records, 
            'records': self.records, 
        })


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
