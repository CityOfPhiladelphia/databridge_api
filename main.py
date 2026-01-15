from fastapi import FastAPI, Depends
from contextlib import asynccontextmanager
from enum import Enum
from carto import Carto
from ago import Ago
import aiohttp


# 1. Create a Manager to hold the session
class SessionManager:
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

# 2. Instantiate the manager at the module level
session_manager = SessionManager()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 3. Start the session when the app starts
    await session_manager.start()
    yield
    # 4. Close the session when the app stops
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
    return {"Session": str(session), 
            "Available Services": [serv.lower() for serv in AVAILABLE_SERVICES.keys()]}


@app.get("/get/")
async def get(
    table: str,
    service: Service = None,
    session: aiohttp.ClientSession = Depends(session_manager),
): 
    if not service: 
        return 'Not Accessing a Service!'
    else: 
        api = AVAILABLE_SERVICES[service.lower()]
        rv = await api.get(session, table)
        return rv