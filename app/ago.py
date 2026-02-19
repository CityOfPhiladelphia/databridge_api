import aiohttp
from fastapi import Request
from .abstract_worker import AbstractWorker, ReturnJson, Meta, Links, Error, GeoJsonFeatureCollection

class Ago(AbstractWorker):
    
    def __init__(self):
        self.name = 'ArcGIS Online'
        self.organization_url = "https://services.arcgis.com/fLeGjb7u4uXqeF9q/ArcGIS/rest/services/"
        self.query_url = "/FeatureServer/0/query"
    
    async def get_count(
        self,
        table: str | None,
        where: str | None,
        session: aiohttp.ClientSession,
        request: Request,
        **kwargs
    ) -> ReturnJson:
        url = f'{self.organization_url}{table}{self.query_url}'
        if not where: 
            where = '1=1'
        params = {
            "where": where,
            "returnCountOnly": 'true', 
            "f": "geojson",
        }
        async with session.get(url, params=params) as response:
            return await self.normalize_rv_count(request, response)

    async def normalize_rv_count(
        self, request: Request, response: aiohttp.ClientResponse
    ) -> ReturnJson:
        links = Links(self=str(request.url))
        meta = Meta(service=self.name, service_url=str(response.url))
        # AGO REST API doesn't respect HTTP status codes
        if response.ok: 
            data = await response.json()
            meta.records_total = data['properties']['count']
            rv = ReturnJson(links=links, meta=meta)
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
        session: aiohttp.ClientSession,
        request: Request,
        **kwargs,
    ) -> ReturnJson:
        url = f'{self.organization_url}{table}{self.query_url}'
        if not where: 
            where = '1=1'
        if not fields: 
            fields = '*'
        else: 
            fields = 'objectid, ' + fields
        params = {
            "where": where,
            "outFields": fields,
            "orderByFields": 'objectid', 
            "f": "geojson",
        }
        if limit: 
            params["resultRecordCount"] = limit
        async with session.get(url, params=params) as response:
            return await self.normalize_rv(request, response)

    async def normalize_rv(
        self, request: Request, response: aiohttp.ClientResponse
    ) -> ReturnJson:
        links = Links(self=str(request.url))
        meta = Meta(service=self.name, service_url=str(response.url))
        # print(f'{await response.text() = }')
        # AGO REST API doesn't respect HTTP status codes
        if response.ok: 
            data = await response.json()
            records = data['features']
            # print(f'{records = }\n')
            gjfc = GeoJsonFeatureCollection(features=records)
            # print(f'{gjfc = }\n')
            meta.record_count = len(gjfc.features)
            try: 
                data['properties']['exceededTransferLimit'] 
                next_url = self.create_next_url(gjfc.features, request)
                links.next=next_url
            except KeyError: 
                pass
            gjfc = GeoJsonFeatureCollection(**data)
            rv = ReturnJson(data=gjfc, links=links, meta=meta)
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
