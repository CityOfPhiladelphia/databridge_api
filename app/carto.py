import aiohttp
from fastapi import Request
from psycopg import sql as psql # Redefine to allow "sql" as a query parameter
from .abstract_worker import AbstractWorker, ReturnJson, Meta, Links, Error, GeoJsonFeatureCollection
from .utils_carto import FULL_QUERY
import citygeo_secrets as cgs

cgs.set_config(log_level='warn')

class Carto(AbstractWorker): 

    def __init__(self): 
        self.name = 'Carto V3 SQL API' 
        self.base_url = "https://gcp-us-east1.api.carto.com/v3/sql/databridge-public-ro/query"
        self.max_records = 1000
        self.secret_name = 'CARTO - New Platform'
        self.public_token = self.get_public_token()
        self.auth_header = {'Authorization': f'Bearer {self.public_token}'}

    def get_public_token(self) -> str: 
        secret = cgs.get_secrets(self.secret_name)
        token = secret[self.secret_name]['Public API Key']
        return token
    
    async def get_count(
        self,
        table: str | None,
        where: str | None,
        session: aiohttp.ClientSession,
        request: Request,
    ) -> ReturnJson:
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
    ) -> ReturnJson:
        links = Links(self=str(request.url))
        meta = Meta(service=self.name, service_url=str(response.url))
        data = await response.json()
        if response.ok:
            meta.record_count = data["rows"][0]["count"]
            rv = ReturnJson(links=links, meta=meta)
            return rv
        else:
            error = Error(
                code=response.status,
                title=f"{self.name} Error",
                detail=data["error"][0],
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
        sql: str | None,
        session: aiohttp.ClientSession,
        request: Request,
        **kwargs,
    ) -> ReturnJson:
        # These queries on their own are unsafe, but we are relying on the safety 
        # checks of the back-end APIs
        if count_only: 
            return await self.get_count(table, where, session, request)
        
        if not sql: 
            if fields: 
                subq_select = psql.SQL(
                    "SELECT ST_Transform(shape, 4326) as shape_1984, objectid AS geojson_id, "
                )
                field_list = [field.strip() for field in fields.split(",")]
                fields_composed = psql.SQL(', ').join([psql.Identifier(field) for field in field_list])
                fields_composed += psql.SQL(' ')
                subq_select += fields_composed 
            else: 
                subq_select = psql.SQL(
                    "SELECT ST_Transform(shape, 4326) as shape_1984, objectid AS geojson_id, * "
                )

            subq_from = psql.SQL('FROM {table} ').format(table=psql.Identifier(table))
            subq = subq_select + subq_from
            if where: 
                subq_where = psql.SQL(f'WHERE {where} ')
                subq = subq + subq_where
            subq += psql.SQL('ORDER BY objectid ')
            if limit is None: 
                limit = self.max_records
            else: 
                limit = min(limit, self.max_records)
            subq_limit = psql.SQL('LIMIT {limit} ').format(limit=psql.Literal(limit))
            subq = subq + subq_limit
            query = psql.SQL(FULL_QUERY).format(subq=subq)
        else: 
            query = psql.SQL(sql)
        params = {'q': query.as_string()}
        # print(f'{query.as_string() = }')
        async with session.get(self.base_url, params=params, headers=self.auth_header) as response:
            return await self.normalize_rv(request, response, limit)

    async def normalize_rv(
        self, request: Request, response: aiohttp.ClientResponse, limit: int
    ) -> ReturnJson:
        links = Links(self=str(request.url))
        meta = Meta(service=self.name, service_url=str(response.url))
        data = await response.json()
        if response.ok: 
            records = data["rows"][0]["jsonb_build_object"]
            # print(f'{records = }\n')
            gjfc = GeoJsonFeatureCollection(**records)
            # print(f'{gjfc = }\n')
            meta.record_count = len(gjfc.features)
            if meta.record_count == limit:
                next_url = self.create_next_url(gjfc.features, request)
                links.next = next_url
            rv = ReturnJson(data=gjfc, links=links, meta=meta)
            return rv
        else: 
            error = Error(
                code=response.status,
                title=f"{self.name} Error",
                detail=data["error"],
            )
            rv = ReturnJson(errors=[error], links=links, meta=meta)
            return rv
