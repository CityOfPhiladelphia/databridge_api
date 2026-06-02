import datetime as dt

import aiohttp
from fastapi import Request

from ..utils.models import (
    Error,
    GeoJsonFeatureCollection,
    Links,
    Meta,
    ReturnJson,
    TableSchema,
)
from .abstract import AbstractWorker, check_fields_valid


class Ago(AbstractWorker):
    def __init__(self):
        self.name = "ArcGIS Online"
        self.organization_url = (
            "https://services.arcgis.com/fLeGjb7u4uXqeF9q/ArcGIS/rest/services/"
        )
        self.query_url = "/FeatureServer/0/query"

    async def get_count(
        self,
        table: str | None,
        where: str | None,
        timeout: float,
        session: aiohttp.ClientSession,
        request: Request,
        **kwargs,
    ) -> ReturnJson:
        url = f"{self.organization_url}{table}{self.query_url}"
        if not where:
            where = "1=1"
        params = {
            "where": where,
            "returnCountOnly": "true",
            "f": "geojson",
        }
        if kwargs["token"]:
            params["token"] = kwargs["token"].removeprefix("Bearer ")
        async with session.get(url, params=params, timeout=timeout) as response:
            return await self.normalize_rv_count(request, response)

    async def normalize_rv_count(
        self, request: Request, response: aiohttp.ClientResponse
    ) -> ReturnJson:
        links = Links(self=str(request.url))
        service_url = self.mask_service_url(request, response)
        meta = Meta(service=self.name, service_url=service_url)
        # AGO REST API doesn't respect HTTP status codes
        if response.ok:
            data = await response.json()
            if "error" not in data:
                meta.records_total = data["properties"]["count"]
                rv = ReturnJson(links=links, meta=meta)
                return rv
            else:
                title = f"{self.name} Error"
                if data["error"]["message"]:
                    title += f": {data['error']['message']}"
                error = Error(
                    code=data["error"]["code"],
                    title=title,
                    detail=data["error"]["details"][0],
                )
                rv = ReturnJson(errors=[error], links=links, meta=meta)
                return rv
        else:
            error_detail = await response.text()
            error = Error(
                code=response.status,
                title=f"{self.name} Error",
                detail=error_detail,
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
        count_only: bool | None,
        out_sr: int | None,
        timeout: float,
        session: aiohttp.ClientSession,
        request: Request,
        **kwargs,
    ) -> ReturnJson:
        schema_cache = kwargs["schema_cache"]
        table_schema = schema_cache.retrieve_table_schema(table)
        valid_fields = table_schema._api_valid_fields

        url = f"{self.organization_url}{table}{self.query_url}"
        if not where:
            where = "1=1"
        if not fields:
            fields = ", ".join([field for field in valid_fields])
        else:
            field_list = [field.strip() for field in fields.split(",")]
            check_fields_valid(field_list, valid_fields, table)
            fields = "objectid, " + fields
        params = {
            "where": where,
            "outFields": fields,
            "outSR": out_sr,
            "orderByFields": "objectid",
            "f": "geojson",
        }
        if limit:
            params["resultRecordCount"] = limit
        if kwargs["token"]:
            params["token"] = kwargs["token"].removeprefix("Bearer ")
        async with session.get(url, params=params, timeout=timeout) as response:
            return await self.normalize_rv(request, response, table_schema)

    async def normalize_rv(
        self, request: Request, response: aiohttp.ClientResponse, table_schema: TableSchema
    ) -> ReturnJson:
        links = Links(self=str(request.url))
        service_url = self.mask_service_url(request, response)
        meta = Meta(service=self.name, service_url=service_url)
        # AGO REST API doesn't respect HTTP status codes
        if response.ok:
            data = await response.json()
            if "error" not in data:
                records = data["features"]
                records = self.harmonize_timestamp_fields(records, table_schema)
                gjfc = GeoJsonFeatureCollection(features=records)
                meta.record_count = len(gjfc.features)
                try:
                    data["properties"]["exceededTransferLimit"]
                    next_url = self.create_next_url(gjfc.features, request)
                    links.next = next_url
                except KeyError:
                    pass
                gjfc = GeoJsonFeatureCollection(**data)
                rv = ReturnJson(data=gjfc, links=links, meta=meta)
                return rv
            else:
                title = f"{self.name} Error"
                if data["error"]["message"]:
                    title += f": {data['error']['message']}"
                error = Error(
                    code=data["error"]["code"],
                    title=title,
                    detail=data["error"]["details"][0],
                )
                rv = ReturnJson(errors=[error], links=links, meta=meta)
                return rv
        else:
            error_detail = await response.text()
            error = Error(
                code=response.status,
                title=f"{self.name} Error",
                detail=error_detail,
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

    def mask_service_url(
        self, request: Request, response: aiohttp.ClientResponse
    ) -> str:
        """Mask a Bearer authorization token in the service_url for safe logging

        Args:
            request (Request): User-initiated request
            response (aiohttp.ClientResponse): Downstream API service response

        Returns:
            str: Safely-masked service url
        """
        service_url = str(response.url)
        if "authorization" in request.headers:
            auth = request.headers["authorization"]
            token = auth.removeprefix("Bearer ")
            service_url = service_url.replace(token, "********")
        return service_url
