from abstract_worker import AbstractWorker, ReturnData, ReturnError
import aiohttp
from fastapi import Request
from psycopg import sql as psql # Redefine to allow "sql" as a query parameter


class Carto(AbstractWorker): 

    def __init__(self): 
        self.name = 'Carto SQL API' 
        self.base_url = "https://phl.carto.com/api/v2/sql"
        self.MAX_RECORDS = 1000

    async def get_count(
        self,
        table: str | None,
        where: str | None,
        session: aiohttp.ClientSession,
        request: Request,
        **kwargs,  # Do not remove
    ) -> ReturnData | ReturnError:
        # These queries on their own are unsafe, but we are relying on the safety 
        # checks of the back-end APIs
        q_select = psql.SQL('SELECT COUNT(*)')
        q_from = psql.SQL(' FROM {table} ').format(table=psql.Identifier(table))
        query = q_select + q_from
        if where: 
            q_where = psql.SQL(f'WHERE {where} ')
            query = query + q_where
        params = {'q': query.as_string()}
        async with session.get(self.base_url, params=params) as response:
            return await self.normalize_rv_count(request, response)

    async def normalize_rv_count(
        self, request: Request, response: aiohttp.ClientResponse
    ) -> ReturnData | ReturnError:
        url = str(request.url)
        api_url = str(response.url)
        data = await response.json()
        service = self.name
        if response.ok:
            records = []
            total_records = data["rows"][0]["count"]
            rv = ReturnData(
                service=service,
                url=url, 
                api_url=api_url,
                records=records,
                record_count=total_records,
            )
            return rv
        else:
            msg = data["error"][0]
            rv = ReturnError(
                service=service,
                url=api_url,
                error_code=response.status,
                error_message=msg,
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
        sql: str | None,
        session: aiohttp.ClientSession,
        request: Request,
        **kwargs,
    ) -> ReturnData | ReturnError:
        # These queries on their own are unsafe, but we are relying on the safety 
        # checks of the back-end APIs
        if not sql: 
            if fields: 
                q_select = psql.SQL('SELECT cartodb_id, ')
                field_list = [field.strip() for field in fields.split(",")]
                fields_composed = psql.SQL(', ').join([psql.Identifier(field) for field in field_list])
                q_select += fields_composed
            else: 
                q_select = psql.SQL('SELECT * ')

            q_from = psql.SQL('FROM {table} ').format(table=psql.Identifier(table))
            query = q_select + q_from
            if where: 
                q_where = psql.SQL(f'WHERE {where} ')
                query = query + q_where
            query += psql.SQL('ORDER BY cartodb_id ')
            if limit is None: 
                limit = self.MAX_RECORDS
            else: 
                limit = min(limit, self.MAX_RECORDS)
            q_limit = psql.SQL('LIMIT {limit} ').format(limit=psql.Literal(limit))
            query = query + q_limit
        else: 
            query = psql.SQL(sql)
        params = {'q': query.as_string()}
        async with session.get(self.base_url, params=params) as response:
            return await self.normalize_rv(request, response, limit)

    async def normalize_rv(
        self, request: Request, response: aiohttp.ClientResponse, limit: int
    ) -> ReturnData | ReturnError:
        url=str(request.url)
        api_url = str(response.url)
        data = await response.json()
        service = self.name
        if response.ok: 
            records = data['rows']
            record_count = data['total_rows']
            if record_count == limit:
                next_url = self.create_next_url(records, request)
            else:
                next_url = ""
            rv = ReturnData(
                service=service,
                url=url, 
                next_url=next_url,
                api_url=api_url,
                records=records,
                record_count=record_count,
            )
            return rv
        else: 
            msg = data['error'][0]
            rv = ReturnError(
                service=service,
                url=api_url,
                error_code=response.status,
                error_message=msg,
            )
            return rv

    def create_next_where_clause(self, data: list[dict]) -> str:
        max_objectid = self.get_data_max_objectid(data, ["cartodb_id"])
        next_where = f"cartodb_id > {max_objectid}"
        return next_where
