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
async def root(session: aiohttp.ClientSession = Depends(session_manager)):
    return {
        "Session": str(session),
        "Available Services": [serv.value for serv in Service],
    }


@app.get("/get")
async def get(
    table: str | None = None,
    fields: str = None,
    where: str = None, 
    limit: int = None, 
    sql: str = None, 
    service: Service = None,
    session: aiohttp.ClientSession = Depends(session_manager),
) -> ReturnData | ReturnError: 
    if not service: 
        return 'Not Accessing a Service!'
    else: 
        api = AVAILABLE_SERVICES[service.lower()]
        if fields: 
            field_list = [field.strip() for field in fields.split(",")]
        else: 
            field_list = None
        rv = await api.get(table, field_list, where, limit, sql, session)
        if isinstance(rv, ReturnData): 
            return rv
        elif isinstance(rv, ReturnError): 
            rv = JSONResponse(status_code=rv.error_code, content=rv.model_dump(mode='json'))
            return rv
