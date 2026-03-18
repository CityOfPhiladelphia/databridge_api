from __future__ import annotations
from .models import ReturnJson, GeoJsonFeature
from abc import ABC, abstractmethod
from fastapi import Request
from fastapi.exceptions import HTTPException
import inspect
import datetime as dt
from collections.abc import Callable


class AbstractWorker(ABC):
    """Abstract base class to ensure worker classes are properly implemented
    See https://www.geeksforgeeks.org/factory-method-python-design-patterns/"""

    CACHE_DURATION = dt.timedelta(minutes=15)
    MAX_RESPONSE_SIZE = (
        1 * 1024 * 1024
    )  # 1MB response limit to not crash user systems (1MB of data is expanding to 10MB response, which is upper limit of what Chrome browser & Postman can handle)
    DEFAULT_SRID = 4326

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
            if param not in ("session", "kwargs", "request"):
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
        if field not in valid_fields:
            raise HTTPException(
                status_code=400,
                headers={"title": "Bad Request"},
                detail=f"Invalid field requested from table '{table}': '{field}'",
            )
