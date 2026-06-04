import aiohttp
import os
import datetime as dt
from fastapi import Request
from psycopg import sql as psql  # Redefine to allow "sql" as a query parameter
from .abstract import AbstractWorker, check_fields_valid
from .models import (
    ReturnJson,
    Meta,
    Links,
    Error,
    GeoJsonFeatureCollection,
    GeoJsonFeature,
    TableSchema,
)


class Databridge(AbstractWorker):
    def __init__(self):
        self.name = "Databridge-Public PostgREST API"
        self.base_url = "https://postgrest-public-dev.citygeo.phila.city"

    async def get_count(
        self,
        table: str | None,
        where: str | None,
        timeout: float,
        session: aiohttp.ClientSession,
        request: Request,
        **kwargs,
    ) -> ReturnJson:
        url = f'{self.base_url}/{table}'
        headers = {"prefer": "count=exact"}
        async with session.head(url, headers=headers, timeout=timeout) as response:
            return await self.normalize_rv_count(request, response)

    async def normalize_rv_count(
        self, request: Request, response: aiohttp.ClientResponse
    ) -> ReturnJson:
        links = Links(self=str(request.url))
        meta = Meta(service=self.name, service_url=str(response.url))
        if response.ok:
            meta.records_total = response.headers.get("Content-Range").split("/")[1]
            rv = ReturnJson(links=links, meta=meta)
            return rv
        else:
            error = Error(
                code=response.status,
                title=f"{self.name} Error",
                detail=response.reason,
            )
            rv = ReturnJson(errors=[error], links=links, meta=meta)
            return rv

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
        request: Request,
        **kwargs,
    ) -> ReturnJson:
        schema_cache = kwargs["schema_cache"]
        table_schema = schema_cache.retrieve_table_schema(table)
        geom_column = table_schema._api_geom_column
        valid_fields = table_schema._api_valid_fields

        url = f'{self.base_url}/{table}'
        params = {}

        if not fields:
            fields = ", ".join([field for field in valid_fields])
        else:
            field_list = [field.strip() for field in fields.split(",")]
            check_fields_valid(field_list, valid_fields, table)
            if geom_column: 
                fields = f'{geom_column}, ' + fields
            fields = "objectid, " + fields
        params = {"select": fields}
        headers = {"prefer": "count=exact"}

        if limit: 
            params["limit"] = limit
        async with session.get(
            url, params=params, headers=headers, timeout=timeout
        ) as response:
            return await self.normalize_rv(request, response, table_schema)

    async def normalize_rv(
        self,
        request: Request,
        response: aiohttp.ClientResponse,
        table_schema: TableSchema | None,
    ) -> ReturnJson:
        links = Links(self=str(request.url))
        meta = Meta(service=self.name, service_url=str(response.url))
        # Now how we gonna transform this to geojson? Should we make database views for that instead?
        data = await response.json()
        if response.ok:
            geojsons = []
            for record in data["rows"]:
                geom_column = table_schema._api_geom_column
                if geom_column:
                    geojson = GeoJsonFeature(
                        id=record.pop("objectid"),
                        properties=record,
                        geometry=record.pop(geom_column),
                    )
                else: 
                    geojson = GeoJsonFeature(
                        id=record.pop("objectid"),
                        properties=record,
                    )
                geojsons.append(geojson)
            gjfc = GeoJsonFeatureCollection(features=geojsons)

            meta.record_count = len(gjfc.features)
            next_url = self.create_next_url(gjfc.features, request)
            links.next = next_url
            rv = ReturnJson(data=gjfc, links=links, meta=meta)
            return rv
        else:
            error = Error(
                code=response.status,
                title=f"{self.name} Error",
                detail=data["error"],
            )
            rv = ReturnJson(errors=[error], links=links, meta=meta)
            return rv

    def harmonize_timestamp_fields(self, records: list[dict], table_schema: TableSchema) -> list[dict]: 
        """Return a consistent representation of timestamp fields. AGO returns 
        timestamp fields as milliseconds since the epoch

        Args:
            records (list[dict]): Data records
            table_schema (TableSchema): TableSchema

        Returns:
            list[dict]: Updated records
        """        
        for record in records:
            for field in record["properties"]:
                if field in table_schema._api_timestamp_fields:
                    if record["properties"][field]: 
                        record["properties"][field] = dt.datetime.fromtimestamp(
                            record["properties"][field] / 1000
                        )
        return records