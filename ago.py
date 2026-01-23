from abstract_worker import AbstractWorker, ReturnData, ReturnError
import aiohttp

class Ago(AbstractWorker):
    
    def __init__(self):
        self.name = 'ArcGIS Online'
        self.organization_url = "https://services.arcgis.com/fLeGjb7u4uXqeF9q/ArcGIS/rest/services/"
        self.query_url = "/FeatureServer/0/query"

    async def get(
        self,
        table: str | None,
        fields: str | None,
        where: str | None,
        limit: int | None, 
        session: aiohttp.ClientSession,
        **kwargs
    ) -> ReturnData | ReturnError:
        url = f'{self.organization_url}{table}{self.query_url}'
        if not where: 
            where = '1=1'
        if not fields: 
            fields = '*'
        params = {
            'where': where, 
            'outFields': fields, 
            'f': 'json'
        }
        async with session.get(url, params=params) as response:
            return await self.normalize_rv(response)

    async def normalize_rv(
        self, response: aiohttp.ClientResponse
    ) -> ReturnData | ReturnError:
        query = str(response.url)
        data = await response.json()
        service = self.name
        # AGO REST API doesn't respect HTTP status codes
        print(f'{data = }')
        if 'features' in data: 
            records = data['features']
            total_records = len(records)
            rv = ReturnData(
                service=service,
                url=query,
                records=records,
                total_records=total_records,
            )
            return rv
        elif 'error' in data: 
            rv = ReturnError(
                service=service, 
                url=query, 
                error_code=data['error']['code'], 
                error_message=data['error']['message'], 
                error_details=data['error']['details'][0]
            )
            return rv