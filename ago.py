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
        field_list: list[str] | None,
        where: str | None,
        limit: int | None, 
        sql: str | None,
        session: aiohttp.ClientSession,
    ) -> ReturnData | ReturnError:
        # These queries on their own are unsafe, but we are relying on the safety 
        # checks of the back-end APIs
        url = f'{self.organization_url}{table}{self.query_url}'
        if not where: 
            where = '1=1'
        if not field_list: 
            out_fields = '*'
        params = {
            'where': where, 
            'outFields': out_fields, 
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
            rv = ReturnData(
                service=service,
                query=query,
                records=records,
                total_records=total_records,
            )
            return rv