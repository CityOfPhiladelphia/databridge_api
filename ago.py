from abstract_worker import AbstractWorker, ReturnJson, Meta, Links, Error
import aiohttp
from fastapi import Request

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
        **kwargs,  # Do not remove
    ) -> ReturnJson:
        url = f'{self.organization_url}{table}{self.query_url}'
        if not where: 
            where = '1=1'
        params = {
            "where": where,
            "returnCountOnly": 'true', 
            "f": "json",
        }
        async with session.get(url, params=params) as response:
            return await self.normalize_rv_count(request, response)

    async def normalize_rv_count(
        self, request: Request, response: aiohttp.ClientResponse
    ) -> ReturnJson:
        links = Links(self=str(request.url))
        meta = Meta(service=self.name, service_url=str(response.url))
        data = await response.json()
        # AGO REST API doesn't respect HTTP status codes
        if 'error' not in data: 
            meta.record_count = data['count']
            rv = ReturnJson(links=links, meta=meta)
            return rv
        else: 
            error = Error(
                code=data["error"]["code"],
                title=f"{self.name} Error: {data['error']['message']}",
                detail=data['error']['details'][0],
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
            "f": "json",
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
        data = await response.json()
        # AGO REST API doesn't respect HTTP status codes
        if 'features' in data: 
            records = data['features']
            meta.record_count=len(records)
            if 'exceededTransferLimit' in data: 
                next_url = self.create_next_url(records, request)
                links.next=next_url
            rv = ReturnJson(data=records, links=links, meta=meta)
            return rv
        elif 'error' in data: 
            error = Error(
                code=data['error']['code'], 
                title=f'{self.name} Error: {data['error']['message']}', 
                detail=data['error']['details'][0]
            )
            rv = ReturnJson(errors=[error], links=links, meta=meta)
            return rv

    def create_next_where_clause(self, data: list[dict]) -> str: 
        max_objectid = self.get_data_max_objectid(data, ['attributes', 'objectid'])
        next_where = f'objectid > {max_objectid}'
        return next_where
