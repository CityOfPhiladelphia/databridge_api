from abstract_worker import AbstractWorker, ReturnData, ReturnError
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
    ) -> ReturnData | ReturnError:
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
    ) -> ReturnData | ReturnError:
        url = str(request.url)
        api_url = str(response.url)
        data = await response.json()
        service = self.name
        # AGO REST API doesn't respect HTTP status codes
        if 'error' not in data: 
            records = []
            total_records = data['count']
            rv = ReturnData(
                service=service,
                url=url,
                api_url=api_url,
                records=records,
                record_count=total_records,
            )
            return rv
        else: 
            rv = ReturnError(
                service=service, 
                url=url, 
                error_code=data['error']['code'], 
                error_message=data['error']['message'], 
                error_details=data['error']['details'][0]
            )
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
    ) -> ReturnData | ReturnError:
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
    ) -> ReturnData | ReturnError:
        url = str(request.url)
        api_url = str(response.url)
        data = await response.json()
        service = self.name
        # AGO REST API doesn't respect HTTP status codes
        if 'features' in data: 
            records = data['features']
            total_records = len(records)
            if 'exceededTransferLimit' in data: 
                next_url = self.create_next_url(records, request)
            else: 
                next_url = ''
            rv = ReturnData(
                service=service,
                url=url,
                next_url=next_url,
                api_url=api_url,
                records=records,
                record_count=total_records,
            )
            return rv
        elif 'error' in data: 
            rv = ReturnError(
                service=service, 
                url=url, 
                api_url=api_url,
                error_code=data['error']['code'], 
                error_message=data['error']['message'], 
                error_details=data['error']['details'][0]
            )
            return rv

    def create_next_where_clause(self, data: list[dict]) -> str: 
        max_objectid = self.get_data_max_objectid(data, ['attributes', 'objectid'])
        next_where = f'objectid > {max_objectid}'
        return next_where
