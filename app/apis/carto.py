import datetime as dt
import os

import aiohttp
from fastapi import Request
from psycopg import sql as psql  # Redefine to allow "sql" as a query parameter

from ..utils.models import (
    Error,
    GeoJsonFeature,
    GeoJsonFeatureCollection,
    Links,
    Meta,
    ReturnJson,
    TableSchema,
)
from ..utils.utils_carto import FULL_QUERY
from .abstract import AbstractWorker, check_fields_valid


class Carto(AbstractWorker):
    def __init__(self):
        self.name = "Carto V3 SQL API"
        self.base_url = (
            "https://gcp-us-east1.api.carto.com/v3/sql/databridge-public-ro/query"
        )
        self.max_records = 1000
        self.public_token = os.environ.get(
            "CARTO_TOKEN"
        )  # token passed in at runtime as env variable. Available at Keeper record "CARTO - New Platform"
        assert self.public_token, "Carto token not provided"
        self.headers = {
            "Authorization": f"Bearer {self.public_token}",
            "Cache-Control": "max-age=1800", # Default Carto Cache to 30 minutes to prevent stale responses
        }

    async def get_count(
        self,
        table: str | None,
        where: str | None,
        timeout: float,
        max_age: int,
        session: aiohttp.ClientSession,
        request: Request,
    ) -> ReturnJson:
        # These queries on their own are unsafe, but we are relying on the safety
        # checks of the back-end APIs
        q_select = psql.SQL("SELECT COUNT(*)")
        q_from = psql.SQL(" FROM {table} ").format(table=psql.Identifier(table))
        query = q_select + q_from
        if where:
            q_where = psql.SQL(f"WHERE {where} ")
            query = query + q_where
        params = {"q": query.as_string()}
        headers = self.headers
        if max_age:
            headers["cache-control"] = f"max-age={max_age}"
        async with session.get(
            self.base_url, params=params, headers=headers, timeout=timeout
        ) as response:
            return await self.normalize_rv_count(request, response)

    async def normalize_rv_count(
        self, request: Request, response: aiohttp.ClientResponse
    ) -> ReturnJson:
        links = Links(self=str(request.url))
        meta = Meta(service=self.name, service_url=str(response.url))
        data = await response.json()
        if response.ok:
            meta.records_total = data["rows"][0]["count"]
            rv = ReturnJson(links=links, meta=meta)
            return rv
        else:
            error = Error(
                code=response.status,
                title=f"{self.name} Error",
                detail=data["error"],
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
        max_age: int,
        session: aiohttp.ClientSession,
        request: Request,
        schema: TableSchema | None,
        **kwargs,
    ) -> ReturnJson:
        # These queries on their own are unsafe, but we are relying on the safety
        # checks of the back-end APIs
        if count_only:
            return await self.get_count(table, where, timeout, max_age, session, request)

        if not sql:
            subq_select = psql.SQL("SELECT objectid AS geojson_id, ")
            if schema.geom_column:
                subq_select += psql.SQL(
                    "ST_Transform({geom_column}, {out_sr}) AS geojson_shape, "
                ).format(
                    geom_column=psql.Identifier(schema.geom_column),
                    out_sr=psql.Literal(out_sr),
                )
            else:
                subq_select += psql.SQL("NULL AS geojson_shape, ")
            if fields:
                field_list = [field for field in fields.split(",")]
                check_fields_valid(field_list, schema.valid_fields, table)
                fields_composed = psql.SQL(", ").join(
                    [psql.Identifier(field) for field in field_list]
                )
                fields_composed += psql.SQL(" ")
                subq_select += fields_composed
            else:
                subq_select += psql.SQL(", ").join(
                    [psql.Identifier(field) for field in schema.valid_fields]
                )

            subq_from = psql.SQL("FROM {table} ").format(table=psql.Identifier(table))
            subq = subq_select + subq_from
            if where:
                subq_where = psql.SQL(f"WHERE {where} ")
                subq = subq + subq_where
            subq += psql.SQL("ORDER BY objectid ")
            if limit is None:
                limit = self.max_records
            else:
                limit = min(limit, self.max_records)
            subq_limit = psql.SQL("LIMIT {limit} ").format(limit=psql.Literal(limit))
            subq = subq + subq_limit
            query = psql.SQL(FULL_QUERY).format(subq=subq)
        else:
            query = psql.SQL(sql)
        params = {"q": query.as_string()}

        headers = self.headers
        if max_age:
            headers["cache-control"] = f"max-age={max_age}"
        async with session.get(
            self.base_url, params=params, headers=headers, timeout=timeout
        ) as response:
            return await self.normalize_rv(request, response, schema, limit, sql)

    async def normalize_rv(
        self,
        request: Request,
        response: aiohttp.ClientResponse,
        schema: TableSchema | None, 
        limit: int,
        sql: str | None,
    ) -> ReturnJson:
        links = Links(self=str(request.url))
        meta = Meta(service=self.name, service_url=str(response.url))
        if int(response.headers["Content-Length"]) >= self.MAX_RESPONSE_SIZE:
            error = Error(
                code="413",
                title="Content Too Large",
                detail="Request less data, preferably 2,000 rows or fewer.",
            )
            rv = ReturnJson(errors=[error], links=links, meta=meta)
            return rv
        data = await response.json()
        if response.ok:
            if not sql:
                records = data["rows"][0]["jsonb_build_object"]['features']
                self.harmonize_timestamp_fields(records, schema)
                gjfc = GeoJsonFeatureCollection(
                    type="FeatureCollection", features=records
                )
            else:
                geojsons = []
                for record in data["rows"]:
                    geojson = GeoJsonFeature(properties=record)
                    geojsons.append(geojson)
                gjfc = GeoJsonFeatureCollection(features=geojsons)

            meta.record_count = len(gjfc.features)
            if not sql and meta.record_count == limit:
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

    def harmonize_timestamp_fields(self, records: list[dict], schema: TableSchema):
        """Coerce to a consistent representation of timestamp fields. Carto returns 
        timestamps in ISO format

        Args:
            records (list[dict]): Data records
            schema (TableSchema): TableSchema
        """
        for record in records:
            for field in record["properties"]:
                if field in schema.timestamp_fields:
                    if record["properties"][field]: 
                        record["properties"][field] = dt.datetime.fromisoformat(
                            record["properties"][field]
                        )
