import os
import time

import aiohttp
from fastapi import Request
from validators import url as valid_url

from ..utils.models import (
    Error,
    GeoJsonFeature,
    GeoJsonFeatureCollection,
    Links,
    Meta,
    ReturnJson,
    TableSchema,
)
from .abstract import AbstractWorker, check_fields_valid


class Databridge(AbstractWorker):
    def __init__(self):
        self.name = "Databridge-Public PostgREST API"
        self.db_url = os.environ.get(
            "POSTGREST_DB_URL",
            default="https://postgrest-public-dev.citygeo.phila.city",
        )  # Used only for counts
        self.rpc_url = f'{self.db_url}/rpc'  # PostgreSQL Function used because of ST_Trasform and GeoJSON preparation
        self.sql_to_postgrest_url = os.environ.get(
            "POSTGREST_SQL_URL",
            default="https://dev-sql-to-postgrest-api.citygeo.phila.city/convert",
        )
        assert valid_url(self.db_url), f'Invalid Databridge db_url: "{self.db_url}"'
        assert valid_url(self.rpc_url), f'Invalid Databridge rpc_url: "{self.rpc_url}"'
        assert valid_url(self.sql_to_postgrest_url), f'Invalid Databridge sql_to_postgrest_url: "{self.sql_to_postgrest_url}"'
        self.max_records = 1000

    async def get_count(
        self,
        table: str | None,
        where: str | None,
        timeout: float,
        session: aiohttp.ClientSession,
        return_json: ReturnJson
    ) -> ReturnJson:
        generated_sql = self.generate_sql(
            table, fields=None, where=where, limit=None, schema=None, count_only=True
        )
        translator_rv = await self.get_postgrest_url(
            generated_sql, session, timeout, return_json
        )
        if isinstance(translator_rv, ReturnJson):
            return translator_rv
        elif isinstance(translator_rv, str):
            postgrest_url = translator_rv

        url = f"{self.db_url}{postgrest_url}"
        headers = {"prefer": "count=exact"}
        async with session.head(url, headers=headers, timeout=timeout) as response:
            return await self.normalize_rv_count(response, return_json)

    async def normalize_rv_count(
        self,
        response: aiohttp.ClientResponse,
        return_json: ReturnJson,
    ) -> ReturnJson:
        return_json.meta.service_url = str(response.url)
        if response.ok:
            return_json.meta.records_total = response.headers.get("Content-Range").split("/")[1]
            return return_json
        else:
            error = Error(code=response.status)
            return_json.errors = [error]
            return return_json

    # Do not remove any unused parameters as they are crucial to the documentation
    async def get(
        self,
        table: str | None,
        fields: str | None,
        where: str | None,
        limit: int | None,
        count_only: bool,
        out_sr: int | None,
        sql: str | None,
        timeout: float,
        session: aiohttp.ClientSession,
        request: Request | None,
        schema: TableSchema, 
        record_latency: bool = False, 
        **kwargs,
    ) -> ReturnJson | None:
        if request: 
            links = Links(self=str(request.url))
        else: 
            links = Links()
        meta = Meta(service=self.name)
        return_json = ReturnJson(links=links, meta=meta)

        if count_only:
            return await self.get_count(table, where, timeout, session, return_json)
        
        params = {}
        if not sql: 
            if limit is None:
                limit = self.max_records
            else:
                limit = min(limit, self.max_records)
            generated_sql = self.generate_sql(table, fields, where, limit, schema, count_only=False)
            if schema.geom_column: 
                params['out_sr'] = out_sr if out_sr else self.DEFAULT_SRID
        else: 
            generated_sql = sql
        translator_rv = await self.get_postgrest_url(
            generated_sql, session, timeout, return_json
        )
        if isinstance(translator_rv, ReturnJson): 
            return translator_rv
        elif isinstance(translator_rv, str): 
            postgrest_url = translator_rv
        if fields: 
            field_list = [field for field in fields.split(",")]
        else: 
            field_list = None

        url = f'{self.rpc_url}{postgrest_url}'
        if record_latency: 
            start_time = time.perf_counter()
        async with session.get(url, params=params, timeout=timeout) as response:
            rv = await self.normalize_rv(
                request, response, schema, sql, limit, return_json, field_list
            )
            if record_latency: 
                self.record_latency(rv, start_time)
            else: 
                return rv

    async def normalize_rv(
        self,
        request: Request | None,
        response: aiohttp.ClientResponse,
        schema: TableSchema | None,
        sql: str | None,
        limit: int | None,
        return_json: ReturnJson,
        field_list: list[str] | None,
    ) -> ReturnJson:
        return_json.meta.service_url = str(response.url)
        data = await response.json()
        if response.ok:
            geojsons = []
            record_count = len(data)
            if sql and record_count >= self.max_records: 
                return self.raise_content_too_large(return_json)
            for record in data: 
                if 'objectid' in record: 
                    objectid = record["objectid"]
                else: 
                    objectid = None
                if schema and schema.geom_column:
                    geometry = record.pop(schema.geom_column)
                else:
                    geometry = None
                if field_list: # Remove any fields not requested by the user, especially objectid. 
                    new_record = {}
                    for field, value in record.items():
                        if field in field_list:
                            new_record[field] = value
                else:
                    new_record = record
                geojson = GeoJsonFeature(
                    id=objectid,
                    properties=new_record,
                    geometry=geometry,
                )
                geojsons.append(geojson)
            gjfc = GeoJsonFeatureCollection(features=geojsons)

            return_json.meta.record_count = record_count
            if request and not sql and return_json.meta.record_count == limit:
                next_url = self.create_next_url(gjfc.features, request)
                return_json.links.next = next_url
            return_json.data = gjfc
            return return_json
        else:
            error = Error(
                code=response.status,
                title=f"{self.name} Error {data['code']}",
                detail=f'{data['details']} {data['message']}',
            )
            return_json.errors = [error]
            return return_json

    def harmonize_timestamp_fields(self): 
        """PostgREST returns ISO-8601 automatically"""        

    async def get_postgrest_url(
        self,
        generated_sql: str | None,
        session: aiohttp.ClientSession,
        timeout: float,
        return_json: ReturnJson
    ) -> str | ReturnJson: 
        """Call the SQL-to-PostgREST translator API for the given SQL. If any 
        error is encountered, create a JSON API response and return that instead

        Args:
            generated_sql (str | None): SQL
            request (Request): The request to this API
            session (aiohttp.ClientSession): Session to make requests with
            timeout (float): Timeout in seconds

        Returns:
            str | ReturnJson: If str, the URL for accessing PostgREST. If a ReturnJson, 
                then an error was encountered
        """        
        async with session.get(
            self.sql_to_postgrest_url, params={'sql': generated_sql}, timeout=timeout
        ) as response:
            data = await response.json()
            if response.ok:
                return data['path']
            else:
                error = Error(
                    code=response.status,
                    title=f"{self.name} Error",
                    detail=data["error"],
                )
                return_json.errors = [error]
                return return_json

    def generate_sql(
        self,
        table: str,
        fields: str | None,
        where: str | None,
        limit: int | None,
        schema: TableSchema,
        count_only: bool,
    ) -> str: 
        """Generate the correct SQL syntax to send to the SQL-to-PostgREST translator
        from user submitted query parameters. 
        Ensure that the SQL contains the objectid and geometry columns. This 
        function only accommodates SELECT, FROM, WHERE, LIMIT, and ORDER BY operators.
        """        
        stmt = "SELECT "
        if count_only: 
            stmt += "* "
        else: 
            if not fields:
                fields = ", ".join([field for field in schema.valid_fields])
            else:
                field_list = [field for field in fields.split(",")]
                check_fields_valid(field_list, schema.valid_fields, table)
                fields = "objectid, " + fields
            if schema.geom_column: 
                fields = f"{schema.geom_column}, " + fields
            stmt += f"{fields} "
        stmt += f"FROM {table} "
        if where: 
            stmt += f"WHERE {where} "
        if not count_only: 
            stmt += "ORDER BY objectid "
            stmt += f"LIMIT {limit} "

        return stmt
    