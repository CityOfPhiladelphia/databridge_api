from __future__ import annotations

import datetime as dt
import inspect
import time
from abc import ABC, abstractmethod
from collections.abc import Callable

from fastapi import Request
from fastapi.exceptions import HTTPException

from ..utils.models import Error, GeoJsonFeature, ReturnJson, TableSchema

NON_USER_API_PARAMS = ("session", "kwargs", "request", "schema")

class AbstractWorker(ABC):
    """Abstract base class to ensure worker classes are properly implemented
    See https://www.geeksforgeeks.org/factory-method-python-design-patterns/"""

    CACHE_DURATION = dt.timedelta(minutes=15)
    MAX_RESPONSE_SIZE = (
        1 * 1024 * 1024
    )  # 1MB response limit to not crash user systems (1MB of data is expanding to 10MB response, which is upper limit of what Chrome browser & Postman can handle)
    MAX_AGE = 31536000  # One year in seconds - used only by Carto but likely overwritten by default Carto infrastructure configuration
    DEFAULT_SRID = 4326
    max_records = 1000

    @abstractmethod
    async def get_count(self) -> ReturnJson:
        """Get the row count of a dataset from the API. Implementation is API-specific"""
        raise NotImplementedError

    @abstractmethod
    async def normalize_rv_count(self) -> ReturnJson:
        """Normalize the data received from the API into a uniform response.
        Implementation is API-specific"""
        raise NotImplementedError

    @abstractmethod
    async def get(self) -> ReturnJson:
        """Get data from the API. Implementation is API-specific"""
        raise NotImplementedError

    @abstractmethod
    async def normalize_rv(self) -> ReturnJson:
        """Normalize the data received from the API into a uniform response.
        Implementation is API-specific"""
        raise NotImplementedError
    
    @abstractmethod
    def harmonize_timestamp_fields(self, records: list[dict], table_schema: TableSchema):
        """Coerce to a consistent representation of timestamp fields. Implementation 
        is API-specific

        Args:
            records (list[dict]): Data records
            table_schema (TableSchema): TableSchema
        """
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
            if param not in NON_USER_API_PARAMS:
                available_parameters.append(param)
        return available_parameters

    def create_next_where_clause(self, features: list[GeoJsonFeature]) -> str:
        """Create the WHERE clause for the NEXT url link to retrieve the next batch
        of data. Any API not using "objectid" would need to overwrite this method

        Args:
            data (list[dict]): Data records

        Returns:
            str: WHERE clause restricting the data to be retrieved
        """
        max_objectid = 0
        for feature in features:
            objectid = int(feature.id)
            max_objectid = max(objectid, max_objectid)
        next_where = f"objectid > {max_objectid}"
        return next_where

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
            new_where = f"({old_where}) AND {next_where}"
        else:
            new_where = next_where
        next_url = str(old_url.include_query_params(where=new_where))
        return next_url

    def raise_content_too_large(self, return_json: ReturnJson) -> ReturnJson: 
        """Raise HTTP 413 Content Too Large error for any API that requests, using 
        the API's max_records value

        Args:
            return_json (ReturnJson): Return JSON object

        Returns:
            ReturnJson: Return JSON object with attached error
        """        
        error = Error(
            code="413",
            title="Content Too Large",
            detail=f"Request fewer than {self.max_records:,} rows.",
        )
        return_json.errors = [error]
        return return_json

    def record_latency(self, rv: ReturnJson, start_time: float): 
        """Record latency information to the API class

        Args:
            rv (ReturnJson): Return JSON object
            start_time (float): Start time of the network call
        """        
        if not rv.errors: 
            elapsed_time = time.perf_counter() - start_time
        else: 
            elapsed_time = float('inf')
        self.latency = elapsed_time
        self.latency_as_of = dt.datetime.now(dt.UTC)
        print(f"API Latency: {self.name} - {self.latency:.4f} seconds - Measured at: {self.latency_as_of.strftime('%Y-%m-%d %H:%M:%S')}")

def check_fields_valid(field_list: list[str], valid_fields: list[str], table: str):
    """Check that the fields requested are valid

    Args:
        field_list (list[str]): List of fields requested
        valid_fields (list[str]): List of valid fields according to table schema
        table (str): Table name

    Raises:
        HTTPException: If a non-existent field was requested
    """
    for field in field_list:
        if field.lower().strip() not in valid_fields:
            raise HTTPException(
                status_code=400,
                headers={"title": "Bad Request"},
                detail=f"Invalid field requested from table '{table}': '{field}'",
            )


def remove_extra_fields(records: list[dict], field_list: list[dict]): 
    """Remove any fields not requested by the user that remain in the downstream
    API response data. This is particularly the case for the objectid field which
    must be requested from AGO even if the user does not specify it so that each
    record has its identifier. Modifies the list of records in place.

    Args:
        records (list[dict]): Data returned from downstream APIs
        field_list (list[dict]): List of fields requested by user
    """    
    for record in records: 
        old_properties = record['properties']
        new_properties = {}
        for field, value in old_properties.items(): 
            if field in field_list: 
                new_properties[field] = value
        record['properties'] = new_properties
