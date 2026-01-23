from abstract_worker import AbstractWorker, ReturnData, ReturnError
import aiohttp
from psycopg import sql as psql # Redefine to allow "sql" as a query parameter


class Carto(AbstractWorker): 

    def __init__(self): 
        self.name = 'Carto SQL API' 
        self.base_url = "https://phl.carto.com/api/v2/sql"

    async def get(
        self,
        table: str | None,
        fields: str | None,
        where: str | None,
        limit: int | None, 
        sql: str | None,
        session: aiohttp.ClientSession,
        **kwargs
    ) -> ReturnData | ReturnError:
        # These queries on their own are unsafe, but we are relying on the safety 
        # checks of the back-end APIs
        if not sql: 
            if fields: 
                q_select = psql.SQL('SELECT ')
                field_list = [field.strip() for field in fields.split(",")]
                fields_composed = psql.SQL(', ').join([psql.Identifier(field) for field in field_list])
                q_select += fields_composed
            else: 
                q_select = psql.SQL('SELECT *')

            q_from = psql.SQL(' FROM {table} ').format(table=psql.Identifier(table))
            query = q_select + q_from
            if where: 
                q_where = psql.SQL(f'WHERE {where} ')
                query = query + q_where
            if limit is not None: 
                q_limit = psql.SQL('LIMIT {limit} ').format(limit=psql.Literal(limit))
                query = query + q_limit
        else: 
            query = psql.SQL(sql)
        url = f'{self.base_url}'
        params = {'q': query.as_string()}
        async with session.get(url, params=params) as response:
            return await self.normalize_rv(response)

    async def normalize_rv(
        self, response: aiohttp.ClientResponse
    ) -> ReturnData | ReturnError:
        query = str(response.url)
        data = await response.json()
        service = self.name
        if response.ok: 
            records = data['rows']
            total_records = data['total_rows']
            rv = ReturnData(
                service=service,
                url=query,
                records=records,
                total_records=total_records,
            )
            return rv
        else: 
            msg = data['error'][0]
            rv = ReturnError(
                service=service,
                url=query,
                error_code=response.status,
                error_message=msg,
            )
            return rv
