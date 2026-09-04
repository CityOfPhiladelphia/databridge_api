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
from .abstract import AbstractWorker, check_fields_valid, remove_extra_fields


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
        return_json: ReturnJson,
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
            return await self.normalize_rv_count(request, response, return_json)

    async def normalize_rv_count(
        self,
        request: Request,
        response: aiohttp.ClientResponse,
        return_json: ReturnJson,
    ) -> ReturnJson:
        service_url = self.mask_service_url(request, response)
        return_json.meta.service_url = service_url
        # AGO REST API doesn't respect HTTP status codes
        if response.ok:
            data = await response.json()
            if "error" not in data:
                return_json.meta.records_total = data["properties"]["count"]
                return return_json
            else:
                return self.raise_ago_data_error(data, return_json)
        else:
            return await self.raise_ago_http_error(response)

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
        schema: TableSchema,
        **kwargs,
    ) -> ReturnJson:
        links = Links(self=str(request.url))
        meta = Meta(service=self.name)
        return_json = ReturnJson(links=links, meta=meta)

        if kwargs['sql']: 
            error = Error(
                code=400,
                title='Bad Request',
                detail=f"'sql' query parameter is invalid for {self.name} service",
            )
            return_json.errors = [error]
            return return_json
        if count_only:
            return await self.get_count(
                table, where, timeout, session, request, return_json, **kwargs
            )

        url = f"{self.organization_url}{table}{self.query_url}"
        if fields:
            field_list = [field for field in fields.split(",")]
            check_fields_valid(field_list, schema.valid_fields, table)
            fields_needed = "objectid, " + fields
        else:
            field_list = None
            fields_needed = ", ".join([field for field in schema.valid_fields])
        if not where:
            where = "1=1"
        params = {
            "where": where,
            "outFields": fields_needed,
            "outSR": out_sr,
            "orderByFields": "objectid",
            "f": "geojson",
        }
        if limit:
            params["resultRecordCount"] = limit
        if kwargs["token"]:
            params["token"] = kwargs["token"].removeprefix("Bearer ")
        async with session.get(url, params=params, timeout=timeout) as response:
            return await self.normalize_rv(request, response, schema, return_json, field_list)

    async def normalize_rv(
        self,
        request: Request,
        response: aiohttp.ClientResponse,
        schema: TableSchema,
        return_json: ReturnJson,
        field_list: list[str] | None
    ) -> ReturnJson:
        service_url = self.mask_service_url(request, response)
        return_json.meta.service_url = service_url
        if response.ok:
            data = await response.json()
            # AGO REST API doesn't always respect HTTP status codes
            if "error" not in data:
                records = data["features"]
                self.harmonize_timestamp_fields(records, schema)
                if field_list: 
                    remove_extra_fields(records, field_list)
                gjfc = GeoJsonFeatureCollection(**data)
                return_json.meta.record_count = len(gjfc.features)
                try:
                    data["properties"]["exceededTransferLimit"]
                    next_url = self.create_next_url(gjfc.features, request)
                    return_json.links.next = next_url
                except KeyError:
                    pass
                return_json.data = gjfc
                return return_json
            else:
                return self.raise_ago_data_error(data, return_json)
        else:
            return await self.raise_ago_http_error(response)

    def harmonize_timestamp_fields(self, records: list[dict], schema: TableSchema): 
        """Coerce to a consistent representation of timestamp fields. AGO returns 
        timestamp fields as milliseconds since the epoch

        Args:
            records (list[dict]): Data records
            schema (TableSchema): TableSchema
        """        
        for record in records:
            for field in record["properties"]:
                if field in schema.timestamp_fields and record["properties"][field]: 
                    record["properties"][field] = dt.datetime.fromtimestamp(  # noqa: DTZ006
                        record["properties"][field] / 1000
                    )

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

    def raise_ago_data_error(self, data: dict, return_json:ReturnJson) -> ReturnJson: 
        """Raise the error return in the AGO data response

        Args:
            data (dict): Returned AGO data
            return_json (ReturnJson): Return JSON object

        Returns:
            ReturnJson: Return JSON object with error attached
        """
        title = f"{self.name} Error"
        if data["error"]["message"]:
            title += f": {data['error']['message']}"
        error = Error(
            code=data["error"]["code"],
            title=title,
            detail=data["error"]["details"][0],
        )
        return_json.errors = [error]
        return return_json

    async def raise_ago_http_error(
        self, response: aiohttp.ClientResponse, return_json: ReturnJson
    ) -> ReturnJson:
        """Raise the HTTP error returned by AGO

        Args:
            response (aiohttp.ClientResponse): HTTP Response
            return_json (ReturnJson): Return JSON object

        Returns:
            ReturnJson: Return JSON object with error attached
        """        
        error_detail = await response.text()
        error = Error(
            code=response.status,
            title=f"{self.name} Error",
            detail=error_detail,
        )
        return_json.errors = [error]
        return return_json
