from fastapi import FastAPI, Depends, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.exceptions import RequestValidationError, HTTPException
from contextlib import asynccontextmanager
from enum import Enum
import aiohttp
from typing import Annotated
from .carto import Carto
from .ago import Ago
from .abstract_worker import AbstractWorker, ReturnJson, Links, Error
from .utils import description, generate_final_response


class SessionManager:
    """A class to manage the aiohttp session for use by the FastAPI app
    """    
    def __init__(self):
        self.session: aiohttp.ClientSession = None

    async def start(self):
        self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30))

    async def stop(self):
        if self.session:
            await self.session.close()
    
    # This is the function we will use in Depends()
    def __call__(self) -> aiohttp.ClientSession:
        return self.session 


session_manager = SessionManager()
carto = Carto()
ago = Ago()
MAP_STR_TO_API: dict[str, AbstractWorker] = {'ago': ago, 'carto': carto} # Note this is the order searched if no API is specified. 
MAP_API_TO_PARAMS: dict[AbstractWorker, list[str]] = {}
for api in MAP_STR_TO_API.values(): 
    MAP_API_TO_PARAMS[api] = api.determine_function_params(api.get)


def make_param_api_descriptions(param: str) -> str: 
    """Create the description line noting for each query parameter which APIs accept it

    Args:
        param (str): Query parameter

    Returns:
        str: Markdown-compatible description taking the form "Used by: AGO, Carto, ..."
    """    
    s = []
    for api in MAP_API_TO_PARAMS: 
        if param in MAP_API_TO_PARAMS[api]: 
            s.append(api.name)
    return "\n\n_Used by:_ " + ", ".join(s)


class Service(str, Enum): 
    AGO = 'ago'
    CARTO = 'carto'

################################################################################
# All FastAPI code should be written below this point #
################################################################################

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Define code to run before the FastAPI app starts and after it shuts down,
    namely to initiate the aiohttp session.

    Args:
        app (FastAPI): App
    """
    await session_manager.start()
    yield
    await session_manager.stop()


app = FastAPI(lifespan=lifespan, title="OIT API Data Wrapper", description=description) 


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    '''Overwrite default FastAPI Validation Error to return consistent with JSON:API Spec'''
    links = Links(self=str(request.url))
    rv_combined = ReturnJson(links=links, errors=[])
    for err in exc.errors(): 
        error = Error(code='422', title=err['type'], detail=f'Message: {err['msg']}. Location: {err['loc']}. Input: \'{err['input']}\'')
        rv_combined.errors.append(error)
    response = JSONResponse(
        status_code=422,
        content=rv_combined.model_dump(mode="json", exclude_none=True),
    )
    return response


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    '''Overwrite default FastAPI HTTP Error to return consistent with JSON:API Spec'''
    links = Links(self=str(request.url))
    error = Error(code=exc.status_code, title=exc.headers['title'], detail=exc.detail)
    rv = ReturnJson(links=links, errors=[error])
    response = JSONResponse(
        status_code=exc.status_code,
        content=rv.model_dump(mode="json", exclude_none=True),
    )
    return response


@ app.get("/", tags=["Routes"])
async def root() -> RedirectResponse:
    """Redirect to the `/docs` endpoint"""
    return RedirectResponse(url='/docs')


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
            description=f"Name of table to retrieve. Either `table` or `sql` parameter is required. Ignored if `sql` parameter is provided.{make_param_api_descriptions('table')}"
        ),
    ] = None,
    fields: Annotated[
        str | None,
        Query(
            description=f"List of fields to retrieve, taking the form _field_1_,_field_2_,... Ignored if `sql` or `count_only` parameters are provided.{make_param_api_descriptions('fields')}"
        ),
    ] = None,
    where: Annotated[
        str | None,
        Query(
            description=f"An SQL _WHERE_ clause to filter data. Ignored if `sql` parameter is provided.{make_param_api_descriptions('where')}"
        ),
    ] = None,
    limit: Annotated[
        int | None,
        Query(
            description=f"Limit to the number of records to return. Ignored if `sql` or `count_only` paramaters are provided.{make_param_api_descriptions('limit')}"
        ),
    ] = None,
    out_sr: Annotated[
        int | None,
        Query(
            description=f"Spatial Reference to return geometric records in. Ignored if dataset is not geometric, or `count_only` or `sql` parameters are provided.{make_param_api_descriptions('count_only')}"
        ),
    ] = None,
    count_only: Annotated[
        bool,
        Query(
            description=f"Return record count of provided query. Ignored if `sql` parameter is provided.{make_param_api_descriptions('count_only')}"
        ),
    ] = False,
    sql: Annotated[
        str | None,
        Query(
            description=f"Raw SQL string to use when retrieving data. Users should request no more than ~2,000 rows to avoid an `HTTP 413` error. Either `table` or `sql` parameter is required.{make_param_api_descriptions('sql')}"
        ),
    ] = None,
    service: Annotated[
        Service | None,
        Query(
            description="Name of API service to use. If not provided, the first API service to locate the table will be used."
        ),
    ] = None,
    session: aiohttp.ClientSession = Depends(session_manager),
) -> ReturnJson | JSONResponse: 
    """Use this endpoint to retrieve data from the available
    services. To select an API service, pass the query parameter `service=<service>`,
    otherwise the first API service to locate the table will be used.
    \nParameters are case-sensitive and those not relevant to a specific service 
    will be ignored."""
    if 'authorization' in request.headers: 
        token = request.headers['authorization']
    else: 
        token = None
    params = {
        'table': table,
        'fields': fields,
        'where': where,
        'limit': limit,
        'out_sr': out_sr, 
        'count_only': count_only, 
        'sql': sql,
        'token': token,
        'session': session,
        'request': request, 
    }
    if sql: 
        if service and MAP_STR_TO_API[service.lower()] != carto:
            raise HTTPException(
                status_code=400,
                detail="SQL parameter can only be used with `service=carto`",
                headers={"title": "Bad Request"},
            )
        rv = await carto.get(**params)
        return generate_final_response(rv)
    if not service: 
        links = Links(self=str(request.url))
        rv_combined = ReturnJson(links=links, errors=[])
        for api in MAP_API_TO_PARAMS:
            if table: 
                rv = await api.get(**params)
            else: 
                raise HTTPException(
                    status_code=400,
                    detail="'table' or 'sql' parameters are required",
                    headers={"title": "Bad Request"},
                )
            
            if not rv.errors: 
                rv.meta.service_available_query_parameters = MAP_API_TO_PARAMS[api]
                return rv
            else:
                rv_combined.errors.append(rv.errors[0])
        return generate_final_response(rv_combined)
    else: 
        api = MAP_STR_TO_API[service.lower()]
        if table: 
            if count_only: 
                rv = await api.get_count(**params)
            else: 
                rv = await api.get(**params) 
        else:
            raise HTTPException(
                status_code=400,
                detail="'table' or 'sql' parameters are required",
                headers={"title": "Bad Request"},
            )
        rv.meta.service_available_query_parameters = MAP_API_TO_PARAMS[api]
        return generate_final_response(rv)
