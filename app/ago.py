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
            "returnCountOnly": "true",
            "f": "geojson",
        }
        if kwargs['token']: 
            params['token'] = kwargs["token"].lstrip("Bearer ")
        async with session.get(url, params=params) as response:
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
            if 'error' not in data: 
                meta.records_total = data['properties']['count']
                rv = ReturnJson(links=links, meta=meta)
                return rv
            else: 
                title = f'{self.name} Error'
                if data['error']['message']: 
                    title += f': {data['error']['message']}'
                error = Error(
                    code=data['error']['code'], 
                    title=title, 
                    detail=data['error']['details'][0]
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
        if not out_sr: 
            out_sr = self.DEFAULT_SRID
        params = {
            "where": where,
            "outFields": fields,
            "outSR": out_sr,
            "orderByFields": 'objectid', 
            "f": "geojson",
        }
        if limit: 
            params["resultRecordCount"] = limit
        if kwargs['token']: 
            params['token'] = kwargs["token"].lstrip("Bearer ")
        async with session.get(url, params=params) as response:
            return await self.normalize_rv(request, response)

    async def normalize_rv(
        self, request: Request, response: aiohttp.ClientResponse
    ) -> ReturnJson:
        links = Links(self=str(request.url))
        service_url = self.mask_service_url(request, response)
        meta = Meta(service=self.name, service_url=service_url)
        # AGO REST API doesn't respect HTTP status codes
        if response.ok: 
            data = await response.json()
            if 'error' not in data: 
                records = data['features']
                gjfc = GeoJsonFeatureCollection(features=records)
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
                title = f'{self.name} Error'
                if data['error']['message']: 
                    title += f': {data['error']['message']}'
                error = Error(
                    code=data['error']['code'], 
                    title=title, 
                    detail=data['error']['details'][0]
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

    def mask_service_url(self, request: Request, response: aiohttp.ClientResponse) -> str: 
        """Mask a Bearer authorization token in the service_url for safe logging

        Args:
            request (Request): User-initiated request
            response (aiohttp.ClientResponse): Downstream API service response

        Returns:
            str: Safely-masked service url
        """        
        service_url = str(response.url)
        if 'authorization' in request.headers: 
            auth = request.headers['authorization']
            token = auth.lstrip('Bearer ')
            service_url = service_url.replace(token, '********')
        return service_url
    