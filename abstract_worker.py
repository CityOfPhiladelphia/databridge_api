from __future__ import annotations
from abc import ABC, abstractmethod
from pydantic import BaseModel
import inspect
from collections.abc import Callable

class ReturnData(BaseModel):
    service: str
    service_available_query_parameters: list[str] = None
    url: str
    total_records: int
    records: list[dict]


class ReturnError(BaseModel): 
    service: str
    service_available_query_parameters: list[str] = None
    url: str
    error_code: int
    error_message: str
    error_details: str | None = None


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
        raise NotImplementedError

    def determine_function_params(self, func: Callable) -> list[str]: 
        """Determine the parameters used in a function so as document which query 
        parameters are accepted by each particular API service

        Args:
            func (Callable): Any function, notably the API class' `get()` function

        Returns:
            list[str]: Names of query parameters available for service's endpoint
        """        
        sig = inspect.signature(func)
        available_parameters = []
        for param in sig.parameters: 
            if param not in ('session', 'kwargs'): 
                available_parameters.append(param)
        return available_parameters
