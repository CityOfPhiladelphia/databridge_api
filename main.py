from fastapi import FastAPI, Depends
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
from enum import Enum
from carto import Carto
from ago import Ago
import aiohttp
from abstract_worker import ReturnData, ReturnError


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
carto = Carto()
ago = Ago()
AVAILABLE_SERVICES = {'ago': ago, 'carto': carto}


class Service(str, Enum): 
    AGO = 'ago'
    CARTO = 'carto'


@app.get("/")
async def root(session: aiohttp.ClientSession = Depends(session_manager)) -> dict[str, list[str]]:
    return {
        "Available Services": [serv.value for serv in Service],
    }

def generate_get_description() -> str: 
    r'''Programmatically generate the API description for the `\get` endpoint to show 
    only the available query parameters for each service'''

    description = '''Use this endpoint to retrieve data from the available services.
Use the following query parameters to refine the data retrieved:'''
    for service in AVAILABLE_SERVICES.values(): 
        service_string = f'''**{service.name}**'''
        for param in service.determine_function_params(func=service.get): 
            service_string += f'\n\n- {param}'
        description += f'\n\n{service_string}'
    description += '\n\nParameters not relevant to a specific service will be ignored'
    return description


@app.get("/get", description=generate_get_description())
async def get_data(
    table: str | None = None,
    fields: str = None,
    where: str = None, 
    limit: int = None, 
    sql: str = None, 
    service: Service = None,
    session: aiohttp.ClientSession = Depends(session_manager),
) -> ReturnData | ReturnError: 
    '''This is the main endpoint for retrieving data, but this docstring will get 
    overwriten by FastAPI via the `description` parameter and `generate_get_description()`'''
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
        if isinstance(rv, ReturnData): 
            return rv
        elif isinstance(rv, ReturnError): 
            rv = JSONResponse(status_code=rv.error_code, content=rv.model_dump(mode='json'))
            return rv
