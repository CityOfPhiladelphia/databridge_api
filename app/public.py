from asyncio import TimeoutError
from typing import Annotated

import aiohttp
from fastapi import APIRouter, Depends, Query, Request
from fastapi.exceptions import HTTPException
from fastapi.responses import JSONResponse, RedirectResponse

from .apis.abstract import AbstractWorker
from .utils.models import Error, Links, Meta, ReturnJson
from .utils.utils import (
    Service,
    api_manager,
    generate_final_response,
    make_param_api_descriptions,
    schema_cache,
    session_manager,
)
from .utils.utils_models import app_version

public_prefix = "/api"
public_router = APIRouter(prefix=public_prefix, tags=["Routes"])


@public_router.get(
    "/get",
    response_model=ReturnJson,
    response_model_exclude_none=True
)
async def get_data(
    request: Request,
    table: Annotated[
        str | None,
        Query(
            description=f"""Name of table to retrieve. Either `table` or `sql`
            parameter is required. Ignored if `sql` parameter is provided. Need an
            example tale? Try `table=dor_parcel`.
            {make_param_api_descriptions(api_manager, "table")}"""
        ),
    ] = None,
    fields: Annotated[
        str | None,
        Query(
            description=f"""List of fields to retrieve, taking the form
            _field_1_,_field_2_,... To receive all fields, do not include this parameter.
            Writing fields=* will return an error. Ignored if `sql` or
            `count_only` parameters are provided.{make_param_api_descriptions(api_manager, "fields")}"""
        ),
    ] = None,
    where: Annotated[
        str | None,
        Query(
            description=f"""An SQL _WHERE_ clause to filter data. Ignored if
            `sql` parameter is provided.{make_param_api_descriptions(api_manager, "where")}"""
        ),
    ] = None,
    limit: Annotated[
        int | None,
        Query(
            description=f"""Limit to the number of records to return. AGO enforces
            a limit specific to each table (frequently 2,000 records); for Carto, this API
            enforces a limit of 1,000 records as Carto otherwise does not have
            limits. Any user-provided limit smaller than those takes precedence.
            Ignored if `sql` or `count_only` paramaters are provided.{make_param_api_descriptions(api_manager, "limit")}"""
        ),
    ] = None,
    out_sr: Annotated[
        int,
        Query(
            description=f"""Spatial Reference to return geometric records in.
            Default SRID is WGS84 (4326). Ignored if dataset is not geometric, or `sql` or `count_only`
            parameters are provided.{make_param_api_descriptions(api_manager, "count_only")}"""
        ),
    ] = AbstractWorker.DEFAULT_SRID,
    count_only: Annotated[
        bool,
        Query(
            description=f"""Return record count of provided query. Ignored if
            `sql` parameter is provided.{make_param_api_descriptions(api_manager, "count_only")}"""
        ),
    ] = False,
    sql: Annotated[
        str | None,
        Query(
            description=f"""Raw SQL string to use when retrieving data. Users
            should request no more than ~2,000 rows to avoid an `HTTP 413` error.
            Either `table` or `sql` parameter is required. Need an example? Try
            `sql=SELECT * FROM DOR_PARCEL LIMIT 10`.{make_param_api_descriptions(api_manager, "sql")}"""
        ),
    ] = None,
    service: Annotated[
        Service | None,
        Query(
            description="""Name of API service to use. If not provided, the first
            API service to locate the table will be used. Ignored if `sql` parameter
            is provided."""
        ),
    ] = None,
    timeout: Annotated[
        float,
        Query(
            description="""Amount of time in seconds to wait for response from downstream APIs
            before raising a timeout error""",
            gt=0,
            lt=300,
        ),
    ] = 30,
    max_age: Annotated[
        int,
        Query(
            description=f"""Request fresh results if cached results are older than _max_age_ in seconds. 0 means request fresh results only, but a request will take longer and demand more server resources to complete. 31,536,000 seconds equals 365 days (default). Use this parameter if you are concerned that table data is incorrect.
            {make_param_api_descriptions(api_manager, "max_age")}""",
            ge=0,
            le=31536000,
        ),
    ] = AbstractWorker.MAX_AGE,
    session: aiohttp.ClientSession = Depends(session_manager), # Same session for all user requests  # noqa: B008
) -> ReturnJson | JSONResponse:
    """Use this endpoint to retrieve data from the available
    services. At a minimum either the `table` or `sql` parameter is required.
    \nParameters are case-sensitive and those not relevant to a specific service
    will be ignored."""
    if "authorization" in request.headers:
        token = request.headers["authorization"]
    else:
        token = None
    if not table and not sql:
        raise HTTPException(
            status_code=400,
            detail="'table' or 'sql' parameters are required",
            headers={"title": "Bad Request"},
        )
    if table and not sql: 
        table = table.lower()
        schema = schema_cache.retrieve_table_schema(table)
    else: 
        schema = None
    params = {
        "table": table,
        "fields": fields,
        "where": where,
        "limit": limit,
        "out_sr": out_sr,
        "count_only": count_only,
        "sql": sql,
        "session": session,
        "timeout": timeout,
        "max_age": max_age,
        "request": request,
        "schema": schema,
        "token": token,
    }
    if not service:
        links = Links(self=str(request.url))
        rv_combined = ReturnJson(links=links, errors=[], meta=Meta())
        for api in api_manager.api_priority_queue:
            try:
                rv = await api.get(**params)
            except TimeoutError:  # noqa: UP041
                api_manager.deprioritize(api)
                error = Error(
                    code=408,
                    title=f"{api.name} Timeout Error",
                    detail="Request could not be completed. Request less data, preferably 2,000 rows or fewer, or alternatively try again.",
                )
                rv_combined.errors.append(error)
            else:
                if not rv.errors:
                    rv.meta.service_available_query_parameters = (
                        api_manager.map_api_to_params[api]
                    )
                    return rv
                else:
                    rv_combined.errors.append(rv.errors[0])
        return generate_final_response(rv_combined)
    else:
        api = api_manager.map_str_to_api[service.lower()]
        try:
            rv = await api.get(**params)
        except TimeoutError:  # noqa: UP041
            raise HTTPException(
                status_code=408,
                detail="Request could not be completed. Request less data, preferably 2,000 rows or fewer, or alternatively try again",
                headers={"title": "Request Timeout"},
            )
        rv.meta.service_available_query_parameters = api_manager.map_api_to_params[api]
        return generate_final_response(rv)


@public_router.get("/api_priority", response_model_exclude_none=True)
async def get_api_priority() -> dict:
    """Return the API names in the order they will be searched if no `service`
    is specified. If an API returns a TimeoutError during a request, then it will be
    placed last in priority order."""
    api_priority = [api.name for api in api_manager.api_priority_queue]
    d = {'api_priority': api_priority, 'databridge_api_version': app_version}
    return d


@public_router.get("/")
async def docs() -> RedirectResponse:
    """Redirect to the `docs` endpoint"""
    return RedirectResponse(url=f"{public_prefix}/docs")
