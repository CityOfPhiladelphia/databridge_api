from __future__ import annotations
from fastapi.responses import JSONResponse
from enum import Enum
import aiohttp
import os
import json
import subprocess
import citygeo_secrets as cgs
from .abstract_worker import AbstractWorker
from .carto import Carto
from .ago import Ago
from .models import ReturnJson
from . import config


class GeomCache:
    """An in-memory cache for the API to quickly determine the name of a table's
    geometry column so that the correct API calls can be made to the downstream
    APIs. This is particularly for Carto which uses raw SQL queries to determine the
    data to return.
    """

    def __init__(self):
        self.script = "./clone_databridge_schemas.sh"
        self.folder = "./databridge-schemas"
        self.cache: dict[str, str | None] = {}
        self.update()

    def update(self):
        """Call the functions necessary to update the geometry cache. Note these
        functions block the API from responding to network requests.
        """
        self.update_local_repo()
        self.search_recursively(self.folder)
        print(f"Cache successfully updated. {len(self.cache):,} tables in cache.")

    def update_local_repo(self):
        """Update the local copy of the databridge-schemas repository. Note that
        this runs a bash script in a subprocess which blocks the API from responding
        until the subprocess completes
        """
        p = subprocess.run(
            self.script, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=15
        )
        try:
            p.check_returncode()
        except subprocess.CalledProcessError:
            print("GeomCache update subprocess error output:\n")
            print(p.stdout.decode())
            raise

    def search_recursively(self, path: str):
        """Recursively search the local copy of the databridge-schemas repository
        for .json files representing table schemas. This function searches for files
        recursively by calling _itself_ recursively.

        Args:
            path (str): Filepath for table's schema
        """
        for file in os.listdir(path):
            new_path = os.path.join(path, file)
            if os.path.isfile(new_path) and new_path.endswith(".json"):
                self.update_cache_table(new_path)
            elif os.path.isdir(new_path):
                self.search_recursively(new_path)

    def update_cache_table(self, path: str):
        """Update a table's geometry column in the cache using the table's schema

        Args:
            path (str): Filepath for table's schema

        Raises:
            AssertionError if multiple geometry columns are found in a table's schema
        """
        table = os.path.splitext(os.path.basename(path))[0]
        with open(path) as f:
            table_schema = json.load(f)
        geom_column = None
        for field in table_schema["fields"]:
            if field["type"] == "geometry":
                assert geom_column is None, (
                    f"Table schema '{table}' contains multiple geometry columns: '{geom_column}' and '{field['name']}'"
                )
                geom_column = field["name"]
        self.cache[table] = {"geom_column": geom_column}


description = """
This wrapper API retrieves data from ArcGIS Online (AGO) and Carto SQL API V3 (Carto) following 
the below specifications: 
1. [JSON:API](https://jsonapi.org/) for API response,
1. [GeoJSON](https://datatracker.ietf.org/doc/html/rfc7946) for returned data, and
1. [OpenAPI](https://www.openapis.org/) for API documentation

Source code: https://github.com/CityOfPhiladelphia/oit_api_wrapper  

### Carto SQL API V3
Carto solely contains public tables, but they 
can only be accessed via a private API token. This token will not be accessible 
to the API user, meaning that the Carto `service_url` will return `HTTP 401 Unauthorized` errors.

### ArcGIS Online
AGO will contain both public and private tables. To access private tables, 
separately generate an access token and then include the token in the following HTTP header: 
```
Authorization: Bearer <token>
```
The AGO `service_url` will mask any bearer authorization token included in the API call, 
meaning this url will not suffice to access the data. If no authorization token was passed 
to the API, then the service url will suffice to access public tables.
"""


def generate_final_response(rv: ReturnJson) -> ReturnJson | JSONResponse: 
    """Return the correct JSON object, either ReturnJson or JSONResponse if
    errors were encountered

    Args:
        rv (ReturnJson): JSON:API spec for returning data

    Returns:
        JSONResponse: FastAPI JSON object with an HTTP Status Code
    """    
    if not rv.errors:
        return rv
    else:
        rv = JSONResponse(
            status_code=int(rv.errors[0].code),
            content=rv.model_dump(mode="json", exclude_none=True),
        )
        return rv


class SessionManager:
    """A class to manage the aiohttp session for use by the FastAPI app"""

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


class Service(str, Enum):
    """Enum to specify the valid query param values to specify each API. 
    This must be updated if any new API is added"""
    AGO = "ago"
    CARTO = "carto"


class Api_Manager:
    def __init__(self):
        """Note method must be updated if any new APIs are added
        """        
        self.map_str_to_api: dict[str, AbstractWorker] = {
            "ago": Ago(),
            "carto": Carto(),
        }  # This is the initial order searched if no API is specified.
        self.map_api_to_params: dict[AbstractWorker, list[str]] = {}
        self.api_priority_queue: list[AbstractWorker] = []
        self.populate_initial_values()

    def populate_initial_values(self):
        for api in self.map_str_to_api.values():
            self.api_priority_queue.append(api)
            self.map_api_to_params[api] = api.determine_function_params(api.get)

    def deprioritize(self, api: AbstractWorker):
        index = self.api_priority_queue.index(api)
        self.api_priority_queue.pop(index)
        self.api_priority_queue.append(api)


def make_param_api_descriptions(api_manager: Api_Manager, param: str) -> str:
    """Create the description line noting for each query parameter which APIs accept it

    Args:
        param (str): Query parameter

    Returns:
        str: Markdown-compatible description taking the form "Used by: AGO, Carto, ..."
    """
    s = []
    for api in api_manager.map_api_to_params:
        if param in api_manager.map_api_to_params[api]:
            s.append(api.name)
    return "\n\n_Used by:_ " + ", ".join(s)


secret = cgs.get_secrets(config.KEEPER_SECRET)
api_token = secret[config.KEEPER_SECRET]["password"]
