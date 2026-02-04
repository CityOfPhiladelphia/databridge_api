from fastapi import FastAPI, Depends, Query
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
from enum import Enum
from carto import Carto
from ago import Ago
import aiohttp
from abstract_worker import ReturnData, ReturnError
from typing import Annotated


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
AVAILABLE_SERVICES = {'ago': ago, 'carto': carto}
SERVICE_PARAMETERS = {}
for api in AVAILABLE_SERVICES.values(): 
    SERVICE_PARAMETERS[api] = api.determine_function_params(api.get)


def make_param_api_descriptions(param: str) -> str: 
    s = []
    for api in SERVICE_PARAMETERS: 
        if param in SERVICE_PARAMETERS[api]: 
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


@ app.get("/")
async def root() -> dict[str, list[str]]:
    return {
        "Available Services": [serv.value for serv in Service],
    }


@app.get("/get")
async def get_data(
    table: Annotated[
        str | None,
        Query(
            description=f"Name of table to retrieve. Not used if `sql` parameter is provided instead.{make_param_api_descriptions('table')}"
        ),
    ] = None,
    fields: Annotated[
        str | None,
        Query(
            description=f"List of fields to retrieve, taking the form _field_1_,_field_2_,... Not used if `sql` parameter is provided instead.{make_param_api_descriptions('fields')}"
        ),
    ] = None,
    where: Annotated[
        str | None,
        Query(
            description=f"An SQL _WHERE_ clause to filter data. Not used if `sql` parameter is provided instead.{make_param_api_descriptions('where')}"
        ),
    ] = None,
    limit: Annotated[
        int | None,
        Query(
            description=f"Limit to the number of records to return. Not used if `sql` parameter is provided instead.{make_param_api_descriptions('limit')}"
        ),
    ] = None,
    sql: Annotated[
        str | None,
        Query(
            description=f"Raw SQL string to use when retrieving data.{make_param_api_descriptions('sql')}"
        ),
    ] = None,
    service: Annotated[
        Service | None,
        Query(
            description="Name of API service to use. If not provided, the first API service to locate the table will be used."
        ),
    ] = None,
    session: aiohttp.ClientSession = Depends(session_manager),
) -> ReturnData | ReturnError: 
    """Use this endpoint to retrieve data from the available
    services. To select an API service, pass the query parameter `service=<service>`,
    otherwise the first API service to locate the table will be used.
    \nParameters not relevant to a specific service will be ignored."""
    if not service: 
        return 'Not Accessing a Service!'
    else: 
        api = AVAILABLE_SERVICES[service.lower()]
        rv = await api.get(
            table=table,
            fields=fields,
            where=where,
            limit=limit,
            sql=sql,
            session=session,
        )
        rv.service_available_query_parameters = SERVICE_PARAMETERS[api]
        if isinstance(rv, ReturnData): 
            return rv
        elif isinstance(rv, ReturnError): 
            rv = JSONResponse(status_code=rv.error_code, content=rv.model_dump(mode='json'))
            return rv
