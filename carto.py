from abstract_worker import AbstractWorker, ReturnData
import aiohttp
from psycopg import sql


class Carto(AbstractWorker): 

    def __init__(self): 
        self.name = 'Carto'
        self.base_url = "https://phl.carto.com/api/v2/sql"

    async def get(self, session: aiohttp.ClientSession, table: str): 
        query = sql.SQL('SELECT * FROM {table} LIMIT 1').format(
            table = sql.Identifier(table)
        )
        
        url = f'{self.base_url}'
        params = {'q': query.as_string()}
        async with session.get(url, params=params) as response:
            return await self.normalize_rv(response)

    async def normalize_rv(self, response: aiohttp.ClientResponse):
        query = str(response.url)
        data = await response.json()
        records = data['rows']
        total_records = data['total_rows']
        rv = ReturnData(query=query, records=records, total_records=total_records)
        return rv
