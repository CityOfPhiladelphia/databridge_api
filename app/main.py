from fastapi import FastAPI, Depends, Query, Request
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
from enum import Enum
import aiohttp
from typing import Annotated
from .carto import Carto
from .ago import Ago
from .abstract_worker import AbstractWorker, ReturnJson, Links


class SessionManager:
    """A class to manage the aiohttp session for use by the FastAPI app
    """    
    def __init__(self):
        self.session: aiohttp.ClientSession = None

    async def start(self):
        self.session = aiohttp.ClientSession()

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


app = FastAPI(lifespan=lifespan) 


@app.get("/")
async def root() -> dict[str, list[str]]:
    return {
        "Available Services": [serv.value for serv in Service],
    }


@app.get("/get", response_model=ReturnJson, response_model_exclude_none=True)
async def get_data(
    request: Request, 
    table: Annotated[
        str | None,
        Query(
            description=f"Name of table to retrieve. Not used if `sql` parameter is provided.{make_param_api_descriptions('table')}"
        ),
    ] = None,
    fields: Annotated[
        str | None,
        Query(
            description=f"List of fields to retrieve, taking the form _field_1_,_field_2_,... Not used if `sql` or `count_only` parameters are provided.{make_param_api_descriptions('fields')}"
        ),
    ] = None,
    where: Annotated[
        str | None,
        Query(
            description=f"An SQL _WHERE_ clause to filter data. Not used if `sql` parameter is provided.{make_param_api_descriptions('where')}"
        ),
    ] = None,
    limit: Annotated[
        int | None,
        Query(
            description=f"Limit to the number of records to return. Not used if `sql` or `count_only` paramaters are provided.{make_param_api_descriptions('limit')}"
        ),
    ] = None,
    count_only: Annotated[
        bool | None,
        Query(
            description=f"Return record count of provided query. Not used if `sql` parameter is provided.{make_param_api_descriptions('count_only')}"
        ),
    ] = None,
    sql: Annotated[
        str | None,
        Query(
            description=f"Raw SQL string to use when retrieving data. Not used if `count_only` parmater is provided.{make_param_api_descriptions('sql')}"
        ),
    ] = None,
    service: Annotated[
        Service | None,
        Query(
            description="Name of API service to use. If not provided, the first API service to locate the table will be used."
        ),
    ] = None,
    session: aiohttp.ClientSession = Depends(session_manager),
) -> ReturnJson: 
    """Use this endpoint to retrieve data from the available
    services. To select an API service, pass the query parameter `service=<service>`,
    otherwise the first API service to locate the table will be used.
    \nParameters not relevant to a specific service will be ignored."""
    params = {
        'table': table,
        'fields': fields,
        'where': where,
        'limit': limit,
        'count_only': count_only, 
        'sql': sql,
        'session': session,
        'request': request, 
    }
    if not service: 
        links = Links(self=str(request.url))
        rv_combined = ReturnJson(links=links, errors=[])
        for api in MAP_API_TO_PARAMS:
            rv = await api.get(**params)
            if not rv.errors: 
                rv.meta.service_available_query_parameters = MAP_API_TO_PARAMS[api]
                return rv
            else:
                rv_combined.errors.append(rv.errors[0])
        response = JSONResponse(
            status_code=rv.errors[0].code,
            content=rv_combined.model_dump(mode="json", exclude_none=True),
        )
        return response
    else: 
        api = MAP_STR_TO_API[service.lower()]
        rv = await api.get(**params)
        rv.meta.service_available_query_parameters = MAP_API_TO_PARAMS[api]
        if not rv.errors:
            return rv
        else:
            rv = JSONResponse(
                status_code=int(rv.errors[0].code),
                content=rv.model_dump(mode="json", exclude_none=True),
            )
            return rv
