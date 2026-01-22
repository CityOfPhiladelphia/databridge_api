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
        if response.ok: 
            records = data['features']
            total_records = len(records)
            available_parameters = self.determine_function_params(self.get)
            rv = ReturnData(
                service=service,
                url=query,
                service_available_query_parameters=available_parameters, 
                records=records,
                total_records=total_records,
            )
            return rv