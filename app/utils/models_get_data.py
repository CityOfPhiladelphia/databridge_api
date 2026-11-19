from typing import Annotated

from fastapi import Query
from pydantic import BaseModel

from ..apis.abstract import AbstractWorker
from .utils import (
    Service,
    api_manager,
    make_param_api_descriptions,
)


class params_get_data(BaseModel): 
    model_config = {"extra": "forbid"}

    table: Annotated[
        str | None,
        Query(
            description=f"""Name of table to retrieve. Either `table` or `sql`
            parameter is required. Ignored if `sql` parameter is provided. Need an
            example tale? Try `table=dor_parcel`.
            {make_param_api_descriptions(api_manager, "table")}"""
        ),
    ] = None
    fields: Annotated[
        str | None,
        Query(
            description=f"""List of fields to retrieve, taking the form
            _field_1_,_field_2_,... To receive all fields, do not include this parameter.
            Writing fields=* will return an error. Ignored if `sql` or
            `count_only` parameters are provided.{make_param_api_descriptions(api_manager, "fields")}"""
        ),
    ] = None
    where: Annotated[
        str | None,
        Query(
            description=f"""An SQL _WHERE_ clause to filter data. Ignored if
            `sql` parameter is provided.{make_param_api_descriptions(api_manager, "where")}"""
        ),
    ] = None
    limit: Annotated[
        int | None,
        Query(
            description=f"""Limit to the number of records to return. AGO enforces
            a limit specific to each table (frequently 2,000 records); for Carto, this API
            enforces a limit of 1,000 records as Carto otherwise does not have
            limits. Any user-provided limit smaller than those takes precedence.
            Ignored if `sql` or `count_only` paramaters are provided.{make_param_api_descriptions(api_manager, "limit")}"""
        ),
    ] = None
    out_sr: Annotated[
        int,
        Query(
            description=f"""Spatial Reference to return geometric records in.
            Default SRID is WGS84 (4326). Ignored if dataset is not geometric, or `sql` or `count_only`
            parameters are provided.{make_param_api_descriptions(api_manager, "count_only")}"""
        ),
    ] = AbstractWorker.DEFAULT_SRID
    x: Annotated[
        float | None,
        Query(
            description=f"""An X coordinate value (longitude) to filter a polygon 
            geometric dataset for records that contain this coordinate. Uses the 
            Spatial Reference ID provided by `out_sr`. Requires `y`, returns an 
            error if used on a non-spatial dataset. Ignored if `sql` or `count_only` 
            parameters are provided.{make_param_api_descriptions(api_manager, "x")}"""
        ),
    ] = None
    y: Annotated[
        float | None,
        Query(
            description=f"""A Y coordinate value (latitude) to filter a polygon 
            geometric dataset for records that contain this coordinate. Uses the 
            Spatial Reference ID provided by `out_sr`. Requires `x`, returns an 
            error if used on a non-spatial dataset. Ignored if `sql` or `count_only` 
            parameters are provided.{make_param_api_descriptions(api_manager, "y")}"""
        ),
    ] = None
    count_only: Annotated[
        bool,
        Query(
            description=f"""Return record count of provided query. Ignored if
            `sql` parameter is provided.{make_param_api_descriptions(api_manager, "count_only")}"""
        ),
    ] = False
    sql: Annotated[
        str | None,
        Query(
            description=f"""Raw SQL string to use when retrieving data. Users
            should request no more than ~2,000 rows to avoid an `HTTP 413` error.
            Either `table` or `sql` parameter is required. Need an example? Try
            `sql=SELECT * FROM DOR_PARCEL LIMIT 10`.{make_param_api_descriptions(api_manager, "sql")}"""
        ),
    ] = None
    service: Annotated[
        Service | None,
        Query(
            description="""Name of API service to use. If not provided, the first
            API service to locate the table will be used. Ignored if `sql` parameter
            is provided."""
        ),
    ] = None
    timeout: Annotated[
        float,
        Query(
            description="""Amount of time in seconds to wait for response from downstream APIs
            before raising a timeout error""",
            gt=0,
            lt=300,
        ),
    ] = 30
    max_age: Annotated[
        int | None,
        Query(
            description=f"""Request fresh results if cached results are older than _max_age_ in seconds. 0 means request fresh results only, but a request will take longer and demand more server resources to complete. 31,536,000 seconds equals 365 days (default). Use this parameter if you are concerned that table data is incorrect.
            {make_param_api_descriptions(api_manager, "max_age")}""",
            ge=0,
            le=31536000,
        ),
    ] = None