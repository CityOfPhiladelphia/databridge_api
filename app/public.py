import os
from asyncio import TimeoutError
from typing import Annotated

import aiohttp
from fastapi import APIRouter, Depends, Query, Request
from fastapi.exceptions import HTTPException
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import ValidationError

from .utils.models import Error, Links, Meta, ReturnJson
from .utils.models_get_data import params_get_data
from .utils.utils import (
    api_manager,
    generate_final_response,
    schema_cache,
    session_manager,
)
from .utils.utils_models import app_version

ROOT_PATH = os.getenv("ROOT_PATH", "/databridge-api/v1")
public_prefix = "/api"
public_router = APIRouter(prefix=public_prefix, tags=["Routes"])


@public_router.get("/get", response_model=ReturnJson, response_model_exclude_none=True)
async def get_data(
    p: Annotated[params_get_data, Query()], # All the query parameters are in the pydantic model params_get_data
    request: Request,
    session: aiohttp.ClientSession = Depends(session_manager),  # Same session for all user requests
) -> ReturnJson | JSONResponse:
    """Use this endpoint to retrieve data from the available
    services. At a minimum either the `table` or `sql` parameter is required.
    \nParameters are case-sensitive and those not relevant to a specific service
    will be ignored."""
    if "authorization" in request.headers:
        token = request.headers["authorization"]
    else:
        token = None
    if not p.table and not p.sql:
        raise HTTPException(
            status_code=400,
            detail="'table' or 'sql' parameters are required",
            headers={"title": "Bad Request"},
        )
    if p.table and not p.sql: 
        p.table = p.table.lower()
        schema = schema_cache.retrieve_table_schema(p.table)
    else: 
        schema = None
    params = {
        "table": p.table,
        "fields": p.fields,
        "where": p.where,
        "limit": p.limit,
        "out_sr": p.out_sr,
        "x": p.x, 
        "y": p.y, 
        "count_only": p.count_only,
        "sql": p.sql,
        "timeout": p.timeout,
        "max_age": p.max_age,
        "request": request,
        "session": session,
        "schema": schema,
        "token": token,
    }
    if not p.service:
        try: 
            links = Links(self=str(request.url))
        except ValidationError: 
            raise HTTPException(
                status_code=400, 
                detail="URL exceeds maximum length", 
                headers={"title": "Bad Request"}
            )
        rv_combined = ReturnJson(links=links, errors=[], meta=Meta())
        for api in api_manager.api_priority_queue:
            invalid_params = api_manager.check_params(api, params)
            if invalid_params: 
                error = Error(
                    code=400,
                    title=f"{api.name} Bad Request",
                    detail=f"{api.name} received invalid parameters: {invalid_params}",
                )
                rv_combined.errors.append(error)
            else: 
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
        api = api_manager.map_str_to_api[p.service.lower()]
        invalid_params = api_manager.check_params(api, params)
        if invalid_params: 
            raise HTTPException(
                status_code=400,
                detail=f"{api.name} received invalid parameters: {invalid_params}",
                headers={"title": "Bad Request"},
            )
        try:
            rv = await api.get(**params)
        except TimeoutError:  # noqa: UP041
            raise HTTPException(
                status_code=408,
                detail="Request could not be completed. Request less data, preferably 2,000 rows or fewer, or alternatively try again",
                headers={"title": "Request Timeout"},
            )
        except ValidationError: 
            raise HTTPException(
                status_code=400, 
                detail="URL exceeds maximum length", 
                headers={"title": "Bad Request"}
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
async def docs(request: Request) -> RedirectResponse:
    """Redirect root path to the docs endpoint for both proxy and local environments."""
    if "x-forwarded-host" in request.headers:
        # Behind MuleSoft proxy
        return RedirectResponse(url=f"{ROOT_PATH}/docs")
    else:
        # Local testing
        return RedirectResponse(url=f"{public_prefix}/docs")


@public_router.get("/redoc", include_in_schema=False)
@public_router.get("/docs", include_in_schema=False)
async def override_docs_html(request: Request):
    """Override default docs to explicitly point to the external proxy URL if the
    request comes with a forwarded-host header"""
    if "x-forwarded-host" in request.headers:
        openapi_url = f"{ROOT_PATH}/openapi.json"
    else:
        openapi_url = f"{public_prefix}/openapi.json"

    if request["path"].endswith("redoc"):
        return get_redoc_html(
            openapi_url=openapi_url, title=f"{request.app.title} - Swagger UI"
        )
    else:
        return get_swagger_ui_html(
            openapi_url=openapi_url, title=f"{request.app.title} - Swagger UI"
        )
