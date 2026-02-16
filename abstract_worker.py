from __future__ import annotations
from abc import ABC, abstractmethod
from pydantic import BaseModel, HttpUrl
from fastapi import Request
import inspect
import functools
from collections.abc import Callable


class GeoJsonGeometry(BaseModel): 
    type: str
    coordinates: list


class GeoJsonFeature(BaseModel): 
    type: str = 'Feature'
    properties: dict
    geometry: GeoJsonGeometry = None


class GeoJsonFeatureCollection(BaseModel): 
    type: str = 'FeatureCollection'
    features: list[GeoJsonFeature]


class Error(BaseModel): 
    code: int
    title: str = None
    detail: str = None


class Links(BaseModel, validate_assignment=True): 
    self: HttpUrl
    next: HttpUrl = None


class Meta(BaseModel, validate_assignment=True): 
    service: str
    service_url: HttpUrl
    service_available_query_parameters: list[str] = None
    record_count: int = None
    records_total: int = None


class ReturnJson(BaseModel, validate_assignment=True): 
    data: GeoJsonFeatureCollection = None # Either data or errors should be returned
    errors: list[Error] = None
    links: Links
    meta: Meta = None


class AbstractWorker(ABC): 
    """Abstract base class to ensure worker classes are properly implemented
    See https://www.geeksforgeeks.org/factory-method-python-design-patterns/"""

    def __init__(self): 
        pass

    @abstractmethod
    async def get_count(self) -> ReturnJson: 
        raise NotImplementedError

    @abstractmethod
    async def normalize_rv_count(self) -> ReturnJson: 
        raise NotImplementedError

    @abstractmethod
    async def get(self) -> ReturnJson: 
        raise NotImplementedError
    
    @abstractmethod
    async def normalize_rv(data) -> ReturnJson:
        raise NotImplementedError

    def determine_function_params(self, func: Callable) -> list[str]: 
        """Determine the parameters used in a function so as to document which query 
        parameters are accepted by each particular API service, ignoring those 
        not passed in by the API user

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
    
    def get_data_max_objectid(self, data: list[dict], fields: list[str]) -> int: 
        """Get the max "objectid" present in the data

        Args:
            data (list[dict]): Data records
            fields (list[str]): List of keys to find the object id, proceeding depth-first

        Returns:
            int: Largest objectid present in this data batch
        """        
        max_objectid = 0
        for row in data:
            objectid = functools.reduce(dict.get, fields, row)
            max_objectid = max(objectid, max_objectid)
        return max_objectid
    
    def create_next_where_clause(self, data: list[dict]) -> str: 
        """Create the WHERE clause to be used in the NEXT url link to retrieve 
        the next set of data. Implementation is API-specific

        Args:
            data (list[dict]): Data records

        Returns:
            str: WHERE clause restricting the data to be retrieved
        """        
        raise NotImplementedError
    
    def create_next_url(self, records: list[dict], request: Request) -> str:
        """Create the url to access the next "page" of data, preserving any existing 
        WHERE clause

        Args:
            records (list[dict]): Data records
            request (Request): User request to this API

        Returns:
            str: URL to access the next page of data
        """        
        old_url = request.url
        old_where = request.query_params.get("where")
        next_where = self.create_next_where_clause(records)
        if old_where:
            new_where = f"{old_where} AND {next_where}"
        else:
            new_where = next_where
        next_url = str(old_url.include_query_params(where=new_where))
        return next_url
