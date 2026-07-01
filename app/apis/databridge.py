import aiohttp
import os
import datetime as dt
from fastapi import Request
from psycopg import sql as psql  # Redefine to allow "sql" as a query parameter
from .abstract import AbstractWorker, check_fields_valid
from ..utils.models import (
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
        self.table_url = "https://postgrest-public-dev.citygeo.phila.city" # Used only for counts
        self.rpc_url = "https://postgrest-public-dev.citygeo.phila.city/rpc" # PostgreSQL Function used because of ST_Trasform and GeoJSON preparation

    async def get_count(
        self,
        table: str | None,
        where: str | None,
        timeout: float,
        session: aiohttp.ClientSession,
        request: Request,
        **kwargs,
    ) -> ReturnJson:
        url = f'{self.table_url}/{table}'
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
        schema: TableSchema, 
        **kwargs,
    ) -> ReturnJson:
        url = f'{self.rpc_url}/{table}'
        params = {}

        if not fields:
            fields = ", ".join([field for field in schema.valid_fields])
        else:
            field_list = [field.strip() for field in fields.split(",")]
            check_fields_valid(field_list, schema.valid_fields, table)
            fields = "objectid, " + fields
        if schema.geom_column: 
            fields = f"{schema.geom_column}, " + fields
        params = {"select": fields, "order": "objectid"}

        if limit: 
            params["limit"] = limit
        if schema.geom_column: 
            params['out_sr'] = out_sr if out_sr else self.DEFAULT_SRID

        async with session.get(
            url, params=params, timeout=timeout
        ) as response:
            return await self.normalize_rv(request, response, schema)

    async def normalize_rv(
        self,
        request: Request,
        response: aiohttp.ClientResponse,
        table_schema: TableSchema | None,
    ) -> ReturnJson:
        links = Links(self=str(request.url))
        meta = Meta(service=self.name, service_url=str(response.url))
        if response.ok:
            data = await response.json()
            geom_column = table_schema.geom_column
            geojsons = []
            for record in data:
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
            text = await response.text()
            error = Error(
                code=response.status,
                title=f"{self.name} Error",
                detail=text,
            )
            rv = ReturnJson(errors=[error], links=links, meta=meta)
            return rv

    def harmonize_timestamp_fields(self, records: list[dict], schema: TableSchema): 
        """Return a consistent representation of timestamp fields. AGO returns 
        timestamp fields as milliseconds since the epoch

        Args:
            records (list[dict]): Data records
            schema (TableSchema): TableSchema
        """        
        for record in records:
            for field in record["properties"]:
                if field in schema.timestamp_fields:
                    if record["properties"][field]: 
                        record["properties"][field] = dt.datetime.fromtimestamp(
                            record["properties"][field] / 1000
                        )
