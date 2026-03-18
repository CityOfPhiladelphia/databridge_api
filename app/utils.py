from __future__ import annotations
from fastapi.responses import JSONResponse
from fastapi.exceptions import HTTPException
from enum import Enum
from asyncio import sleep
import aiohttp
import os
import json
import re
from .abstract import AbstractWorker
from .carto import Carto
from .ago import Ago
from .models import ReturnJson


class SchemaCache:
    """An in-memory cache for the API to know a table's fields in order to determine 
    both the fields to request and which field is the geometry column so that the 
    correct API calls can be made to the downstream APIs. The latter point is particularly 
    for Carto which uses raw SQL queries to determine the data to return.
    """

    def __init__(self):
        self.folder = "/var/git/databridge-schemas"
        self.commit_check_delay = 300
        self.latest_commit: str = None
        self.cache: dict[str, str | None] = {}
        self.invalid_fields: list[str] = [
            'shape',                # Carto
            'Shape__Area',          # AGO (some tables, such as dor_parcel)
            'Shape__Length',        # AGO (some tables, such as dor_parcel)
            'gdb_geomattr_data'     # AGO (some tables, such as dor_parcel)
        ]

    async def loop_commit_check(self): 
        """Run a continuous asynchronous loop to quickly absorb any updates to the 
        schemas repository
        """        
        while True: 
            self.check_latest_commit()
            await sleep(self.commit_check_delay)
    
    def check_latest_commit(self): 
        """Check if the API has the latest commit of the schemas repository
        """        
        print('Checking latest commit')
        path = os.path.join(self.folder, '.git')
        if os.path.isdir(path): # Local development 
            with open(os.path.join(path, 'refs', 'heads', 'main')) as f: 
                commit = f.readline().strip()
        elif os.path.isfile(path): # Prod environment 
            with open(path) as f: 
                line = f.readline().strip()
                commit = re.match(r"\w+$", line)[0]
        if commit != self.latest_commit: 
            self.update()
            self.latest_commit = commit
    
    def update(self):
        """Call the functions necessary to update the geometry cache. Note these
        functions block the API from responding to network requests.
        """
        print('Updating SchemaCache')
        assert os.path.isdir(self.folder), f"databridge-schemas repo not found at {self.folder}!!"
        replacement_cache = self.search_recursively(self.folder)
        self.cache = replacement_cache
        print(f"Cache successfully updated. {len(self.cache):,} tables in cache.")


    def search_recursively(self, path: str, replacement_cache = {}):
        """Recursively search the local copy of the databridge-schemas repository
        for .json files representing table schemas. This function searches for files
        recursively by calling _itself_ recursively.

        Args:
            path (str): Filepath for table's schema
        """
        for file in os.listdir(path):
            new_path = os.path.join(path, file)
            if os.path.isfile(new_path) and new_path.endswith(".json"):
                table, table_schema = self.return_table_schema(new_path)
                assert table not in replacement_cache, f'Two separate tables have the same name: {table}'
                replacement_cache[table] = table_schema
            elif os.path.isdir(new_path):
                if not file.startswith('.'): # Ignore .venv, .git, etc.
                    replacement_cache = self.search_recursively(new_path, replacement_cache)
        return replacement_cache

    def return_table_schema(self, path: str) -> tuple[str, dict]:
        """Return the schema for a table 

        Args:
            path (str): Filepath for table's schema
        """
        table = os.path.splitext(os.path.basename(path))[0]
        with open(path) as f:
            schema = json.load(f)
            self.parse_schema(table, schema)
        return table, schema
    
    def parse_schema(self, table: str, schema: dict) -> str|None: 
        """Update the schema with its geometry column and valid fields

        Args:
            table (str): Table name
            schema_fields (list[dict]): List of schema fields

        Returns:
            str|None: Name of geometry column, or None if it does not exist
        
        Raises: 
            AssertionError: If multiple geometry columns exist
        """        
        schema['_api_internal_geom_column'] = None
        schema['_api_internal_valid_fields'] = []
        for field in schema['fields']: 
            if field['type'] == 'geometry': 
                assert schema['_api_internal_geom_column'] is None, f'Table "{table}" has multiple geometry columns: {[schema['_api_internal_geom_column'], field['name']]}'
                schema['_api_internal_geom_column'] = field['name']
            if field['name'] not in self.invalid_fields: 
                schema["_api_internal_valid_fields"].append(field["name"])

    def retrieve_table_schema(self, table: str): 
        try:    
            return self.cache[table]
        except KeyError:
            raise HTTPException(
                status_code=404,
                headers={"title": "Not Found"},
                detail=f"Schema not found for table '{table}'",
            )


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