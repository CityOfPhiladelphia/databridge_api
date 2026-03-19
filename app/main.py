from fastapi import FastAPI, Depends, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.exceptions import RequestValidationError, HTTPException
from contextlib import asynccontextmanager
import aiohttp
from asyncio import TimeoutError, create_task
from typing import Annotated
from .models import ReturnJson, Links, Error
from .utils import (
    AbstractWorker,
    Api_Manager,
    SchemaCache,
    SessionManager,
    Service,
    description,
    generate_final_response,
    make_param_api_descriptions,
)


session_manager = SessionManager()
schema_cache = SchemaCache()
api_manager = Api_Manager()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Define code to run before the FastAPI app starts and after it shuts down,
    namely to initiate the aiohttp session.

    Args:
        app (FastAPI): App
    """
    schema_cache.check_latest_commit()
    commit_check_task = create_task(schema_cache.loop_commit_check())
    await session_manager.start()
    yield
    commit_check_task.cancel()
    await session_manager.stop()


app = FastAPI(lifespan=lifespan, title="OIT API Data Wrapper", description=description)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Overwrite default FastAPI Validation Error to return consistent with JSON:API Spec"""
    links = Links(self=str(request.url))
    rv_combined = ReturnJson(links=links, errors=[])
    for err in exc.errors():
        error = Error(
            code="422",
            title=err["type"],
            detail=f"Message: {err['msg']}. Location: {err['loc']}. Input: '{err['input']}'",
        )
        rv_combined.errors.append(error)
    response = JSONResponse(
        status_code=422,
        content=rv_combined.model_dump(mode="json", exclude_none=True),
    )
    return response


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """Overwrite default FastAPI HTTP Error to return consistent with JSON:API Spec"""
    links = Links(self=str(request.url))
    error = Error(code=exc.status_code, title=exc.headers["title"], detail=exc.detail)
    rv = ReturnJson(links=links, errors=[error])
    response = JSONResponse(
        status_code=exc.status_code,
        content=rv.model_dump(mode="json", exclude_none=True),
    )
    return response


@app.get(
    "/get",
    response_model=ReturnJson,
    response_model_exclude_unset=True,
    tags=["Routes"],
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
    session: aiohttp.ClientSession = Depends(session_manager),
) -> ReturnJson | JSONResponse:
    """Use this endpoint to retrieve data from the available
    services. At a minimum either the `table` or `sql` parameter is required.
    \nParameters are case-sensitive and those not relevant to a specific service
    will be ignored."""
    if "authorization" in request.headers:
        token = request.headers["authorization"]
    else:
        token = None
    params = {
        "table": table,
        "fields": fields,
        "where": where,
        "limit": limit,
        "out_sr": out_sr,
        "count_only": count_only,
        "sql": sql,
        "token": token,
        "session": session,
        "timeout": timeout,
        "request": request,
        "schema_cache": schema_cache,
    }
    if sql:
        if service and service.lower() != "carto":
            raise HTTPException(
                status_code=400,
                detail="SQL parameter can only be used with `service=carto`",
                headers={"title": "Bad Request"},
            )
        try:
            rv = await api_manager.map_str_to_api["carto"].get(**params)
        except TimeoutError:
            raise HTTPException(
                status_code=408,
                detail="Request could not be completed. Request less data, preferably 2,000 rows or fewer, or alternatively try again.",
                headers={"title": "Request Timeout"},
            )
        return generate_final_response(rv)
    if not service:
        links = Links(self=str(request.url))
        rv_combined = ReturnJson(links=links, errors=[])
        for api in api_manager.map_api_to_params:
            if table:
                try:
                    rv = await api.get(**params)
                except TimeoutError:
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
            else:
                raise HTTPException(
                    status_code=400,
                    detail="'table' or 'sql' parameters are required",
                    headers={"title": "Bad Request"},
                )
        return generate_final_response(rv_combined)
    else:
        api = api_manager.map_str_to_api[service.lower()]
        if table:
            try:
                if count_only:
                    rv = await api.get_count(**params)
                else:
                    rv = await api.get(**params)
            except TimeoutError:
                raise HTTPException(
                    status_code=408,
                    detail="Request could not be completed. Request less data, preferably 2,000 rows or fewer, or alternatively try again",
                    headers={"title": "Request Timeout"},
                )
        else:
            raise HTTPException(
                status_code=400,
                detail="'table' or 'sql' parameters are required",
                headers={"title": "Bad Request"},
            )
        rv.meta.service_available_query_parameters = api_manager.map_api_to_params[api]
        return generate_final_response(rv)


@app.get("/api_priority", tags=["Routes"])
async def get_api_priority() -> list:
    """Return the API names in the order they will be searched if no `service`
    is specified. If an API returns a TimeoutError during a request, then it will be
    placed last in priority order."""
    return [api.name for api in api_manager.api_priority_queue]


@app.get("/", tags=["Routes"])
async def docs() -> RedirectResponse:
    """Redirect to the `/docs` endpoint"""
    return RedirectResponse(url="/docs")
