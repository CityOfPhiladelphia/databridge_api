from __future__ import annotations

import datetime as dt
import json
import os
from asyncio import sleep
from enum import Enum

import aiohttp
from fastapi.exceptions import HTTPException
from fastapi.responses import JSONResponse

from ..apis.abstract import AbstractWorker
from ..apis.ago import Ago
from ..apis.carto import Carto
from ..apis.databridge import Databridge
from .models import ReturnJson, TableSchema


class SchemaCache:
    """An in-memory cache for the API to know a table's fields in order to determine
    both the fields to request and which field is the geometry column so that the
    correct API calls can be made to the downstream APIs. The latter point is particularly
    for Carto which uses raw SQL queries to determine the data to return.
    """

    def __init__(self):
        self._prod_folder = "/var/git/databridge-schemas"
        self._local_dev_folder = "/scripts/databridge-schemas"
        self.folder = self.set_folder()
        self.commit_check_delay = 300
        self.latest_repo_target: str = None
        self.cache: dict[str, TableSchema] = {}
        self.invalid_fields: list[str] = [
            "shape",  # Carto
            "Shape__Area",  # AGO (some tables, such as dor_parcel)
            "Shape__Length",  # AGO (some tables, such as dor_parcel)
            "gdb_geomattr_data",  # AGO (some tables, such as dor_parcel)
        ]
        self.latest_check: dt.datetime = None
        self.latest_update: dt.datetime = None

    def set_folder(self): 
        if os.path.isdir(self._prod_folder): 
            return self._prod_folder
        elif os.path.isdir(self._local_dev_folder): 
            return self._local_dev_folder
        else: 
            raise AssertionError(
                f'databridge-schemas repo not found at "{self._prod_folder}" or "{self._local_dev_folder}"'
            )
    
    async def loop_commit_check(self):
        """Run a continuous asynchronous loop to quickly absorb any updates to the
        schemas repository
        """
        while True:
            self.check_latest_commit()
            await sleep(self.commit_check_delay)

    def check_latest_commit(self):
        # Resolve the symlink to its actual current directory
        # Or if we're locally developing, to the full path of the repo.
        # Either will work with realpath().
        # (e.g., /var/git/.worktrees/<some_commit_hash>/)
        current_target = os.path.realpath(self.folder)
        self.latest_check = dt.datetime.now(tz=dt.UTC)

        if getattr(self, 'latest_repo_target', None) != current_target:
            print(f"New symlink target detected: {current_target} Updating SchemaCache.")
            try:
                # Offload the blocking I/O to a separate thread
                self.latest_repo_target = current_target
                # Overwrite the folder path with the new target
                self.folder = current_target
                self.update()

            except FileNotFoundError:
                # Expected race condition: git-sync swapped directories while we were reading.
                # Abort this attempt; the loop will try again on the next tick.
                print("Update aborted: git-sync modified files during read.")
            except Exception as e:  # noqa: BLE001
                print(f"Unexpected error updating cache: {e}")
        else:
            print(f'No changes detected. {current_target =}, {self.latest_repo_target =}')

    def update(self):
        """Call the functions necessary to update the geometry cache. Note these
        functions block the API from responding to network requests.
        """
        print("Updating SchemaCache")
        self.latest_update = dt.datetime.now(tz=dt.UTC)
        replacement_cache = self.search_recursively(self.folder)
        self.cache = replacement_cache
        print(f"Cache successfully updated. {len(self.cache):,} tables in cache.")

    def search_recursively(self, path: str, replacement_cache: dict | None = None):
        """Recursively search the local copy of the databridge-schemas repository
        for .json files representing table schemas. This function searches for files
        recursively by calling _itself_ recursively.

        Args:
            path (str): Filepath for table's schema
        """
        if replacement_cache is None: 
            replacement_cache = {}
        for file in os.listdir(path):
            new_path = os.path.join(path, file)
            if os.path.isfile(new_path) and new_path.endswith(".json"):
                table, table_schema = self.return_table_schema(new_path)
                assert table not in replacement_cache, (
                    f"Two separate tables have the same name: {table}"
                )
                replacement_cache[table] = table_schema
            elif os.path.isdir(new_path):
                if not file.startswith("."):  # Ignore .venv, .git, etc.
                    replacement_cache = self.search_recursively(
                        new_path, replacement_cache
                    )
        return replacement_cache

    def return_table_schema(self, path: str) -> tuple[str, TableSchema]:
        """Return the schema for a table

        Args:
            path (str): Filepath for table's schema
        """
        table = os.path.splitext(os.path.basename(path))[0]
        with open(path) as f:
            schema = json.load(f)
            table_schema = self.parse_schema(table, schema)
        return table, table_schema

    def parse_schema(self, table: str, schema: dict) -> TableSchema:
        """Update the schema with valid fields, geometry column, and timestamp fields

        Args:
            table (str): Table name
            schema (dict): Table schema

        Returns:
            TableSchema: Parsed version of table schema

        Raises:
            AssertionError: If multiple geometry columns exist
        """
        table_schema = TableSchema(**schema)
        for field in table_schema.fields:
            if field.name not in self.invalid_fields:
                table_schema.valid_fields.append(field.name)
            if field.type == "geometry":
                assert table_schema.geom_column is None, (
                    f'Table "{table}" has multiple geometry columns: {[table_schema.geom_column, field.name]}'
                )
                table_schema.geom_column = field.name
            elif field.type.startswith("timestamp"):
                table_schema.timestamp_fields.append(field.name)
        return table_schema

    def retrieve_table_schema(self, table: str) -> dict:
        """Retrieve the schema for a table from the SchemaCache

        Args:
            table (str): Table name

        Raises:
            HTTPException: If table schema not found

        Returns:
            dict: Table schema
        """
        try:
            return self.cache[table]
        except KeyError:
            raise HTTPException(
                status_code=404,
                headers={"title": "Not Found"},
                detail=f"Schema not found for table '{table}'",
            )


description = """
This wrapper API retrieves data from Databridge-Public database, ArcGIS Online (AGO), and Carto SQL API V3 (Carto) following
the below specifications:
1. [JSON:API](https://jsonapi.org/) for API response,
1. [GeoJSON](https://datatracker.ietf.org/doc/html/rfc7946) for returned data, and
1. [OpenAPI](https://www.openapis.org/) for API documentation


Note there may be small differences in data values for the same table between the
APIs specifically in geometry and timestamp fields due to those APIs
internal configurations

**Source code: https://github.com/CityOfPhiladelphia/databridge_api**

### Databridge-Public
The Databridge-Public contains public tables only; it is configured with a PostgREST server. 

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
    DATABRIDGE = "databridge"


class Api_Manager:
    """A class to manage the downstream APIs so they can be accessed in different
    ways and they can be rearranged in a "priority queue".
    """

    def __init__(self):
        """Note this method must be updated if any new APIs are added"""
        self.map_str_to_api: dict[str, AbstractWorker] = {
            "databridge": Databridge(),
            "carto": Carto(),
            "ago": Ago(),
        }  # This is the initial priority order searched if no API is specified, and is the query param the user must submit
        self.map_api_to_params: dict[AbstractWorker, list[str]] = {}
        self.api_priority_queue: list[AbstractWorker] = []
        self.populate_initial_values()
        self.reorder_priority_queue_delay = 300

    def populate_initial_values(self):
        """Populate the initial attributes for accessing information about the APIs"""
        for api in self.map_str_to_api.values():
            self.api_priority_queue.append(api)
            self.map_api_to_params[api] = api.determine_function_params(api.get)

    def deprioritize(self, api: AbstractWorker):
        """Deprioritize an API by changing its position to last in priority queue
        order. This is intended to only be called when a user did not specify the
        API, and an API returned a TimeoutError, so that functioning APIs are
        prioritized first for data retrieval.

        Args:
            api (AbstractWorker): API class
        """
        index = self.api_priority_queue.index(api)
        self.api_priority_queue.pop(index)
        self.api_priority_queue.append(api)

    async def reorder_priority_queue(self): 
        """Run a continuous async loop to reorder the API priority queue 
        according to the default ordering by pinging the table "rtt_summary",
        deprioritizing any unhealthy APIs with latency >= 1 second. 
        """        
        HEALTHY_THRESHOLD = 5.0
        while True: 
            healthy_queue = []
            unhealthy_queue = []
            for api in self.map_str_to_api.values(): # Default ordering
                try: 
                    params = {
                        "table": "rtt_summary",
                        "fields": None,
                        "where": None,
                        "limit": 1,
                        "count_only": False,
                        "out_sr": AbstractWorker.DEFAULT_SRID,
                        "sql": None,
                        "session": session_manager(),
                        "timeout": 5,
                        "request": None,
                        "schema": schema_cache.retrieve_table_schema("rtt_summary"),
                        "token": None,
                        "max_age": api.MAX_AGE, 
                        "record_latency": True,
                    }
                    await api.get(**params)
                    if api.latency < HEALTHY_THRESHOLD: 
                        healthy_queue.append(api)
                    else: 
                        unhealthy_queue.append(api)
                except Exception as e:  # noqa: BLE001
                    print(f"ERROR in background task: {type(e).__name__}: {e}")
                    unhealthy_queue.append(api)
            unhealthy_queue.sort(key=lambda api: api.latency) # Sort the unhealthy APIs by latency asc
            self.api_priority_queue = healthy_queue + unhealthy_queue
            print(f'Queue: {[api.name for api in self.api_priority_queue]}\n')
            await sleep(self.reorder_priority_queue_delay)


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


schema_cache = SchemaCache()
api_manager = Api_Manager()
session_manager = SessionManager()
