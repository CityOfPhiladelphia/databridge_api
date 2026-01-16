from abstract_worker import AbstractWorker, ReturnData
import aiohttp
from psycopg import sql # Carto uses PostgreSQL database as its backend


class Carto(AbstractWorker): 

    def __init__(self): 
        self.name = 'Carto'
        self.base_url = "https://phl.carto.com/api/v2/sql"

    async def get(
        self, table: str, field_list: list[str] | None, session: aiohttp.ClientSession
    ) -> ReturnData:
        if field_list: 
            select = sql.SQL('SELECT')
            join_list = sql.SQL(', ').join([sql.Identifier(field) for field in field_list])
            select += join_list
        else: 
            select = sql.SQL('SELECT *')

        query = select + sql.SQL('FROM {table} LIMIT 1').format(
            table = sql.Identifier(table)
        )
        
        url = f'{self.base_url}'
        params = {'q': query.as_string()}
        async with session.get(url, params=params) as response:
            return await self.normalize_rv(response)

    async def normalize_rv(self, response: aiohttp.ClientResponse) -> ReturnData:
        query = str(response.url)
        data = await response.json()
        records = data['rows']
        total_records = data['total_rows']
        rv = ReturnData(query=query, records=records, total_records=total_records)
        return rv
