import aiohttp
import datetime as dt
from fastapi import Request
from psycopg import sql as psql # Redefine to allow "sql" as a query parameter
from .abstract_worker import AbstractWorker, ReturnJson, Meta, Links, Error, GeoJsonFeatureCollection, GeoJsonFeature
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
        self.geom_cache = {}

    def get_public_token(self) -> str: 
        secret = cgs.get_secrets(self.secret_name)
        token = secret[self.secret_name]['Public API Key']
        return token
    
    async def check_geom_cache(self, table: str, **kwargs): 
        if table in self.geom_cache: 
            if dt.datetime.now() - self.geom_cache[table]['retrieved_at'] <= self.CACHE_DURATION: 
                return self.geom_cache[table]
        return None
    
    async def get_geometry(self, table: str, session: aiohttp.ClientSession, **kwargs): 
        """ Determine if a table in Carto is geometric or not. This info changes 
        the SQL query sent to Carto to retrieve data 

        Args:
            table (str): _description_
            session (aiohttp.ClientSession): _description_

        Returns:
            _type_: _description_
        """        
        cache_result = await self.check_geom_cache(table)
        if not cache_result:
            query = psql.SQL("SELECT * FROM {table} LIMIT 1").format(
                table=psql.Identifier(table)
            )
            params = {'q': query.as_string()}
            async with session.get(
                self.base_url, params=params, headers=self.auth_header
            ) as response:
                return await self.normalize_rv_geometry(table, response)

    async def normalize_rv_geometry(
        self, table: str, response: aiohttp.ClientResponse
    ) -> ReturnJson:
        meta = Meta(service=self.name, service_url=str(response.url))
        data = await response.json()
        if response.ok:
            geometry = None
            for col in data['schema']: 
                if col['type'] == 'geometry': 
                    geometry = col['name']
                    break
            self.geom_cache[table] = {
                "geometry": geometry,
                "retrieved_at": dt.datetime.now(),
            }
            rv = ReturnJson(meta=meta)
            return rv
        else:
            error = Error(
                code=response.status,
                title=f"{self.name} Error",
                detail=data["error"],
            )
            rv = ReturnJson(errors=[error], meta=meta)
            return rv
    
    async def get_count(
        self,
        table: str | None,
        where: str | None,
        session: aiohttp.ClientSession,
        request: Request,
        **kwargs,
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
        async with session.get(
            self.base_url, params=params, headers=self.auth_header
        ) as response:
            return await self.normalize_rv_count(request, response)

    async def normalize_rv_count(
        self, request: Request, response: aiohttp.ClientResponse
    ) -> ReturnJson:
        links = Links(self=str(request.url))
        meta = Meta(service=self.name, service_url=str(response.url))
        data = await response.json()
        if response.ok:
            meta.records_total = data["rows"][0]["count"]
            rv = ReturnJson(links=links, meta=meta)
            return rv
        else:
            error = Error(
                code=response.status,
                title=f"{self.name} Error",
                detail=data["error"],
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
        count_only: bool,
        out_sr: int | None,
        sql: str | None,
        session: aiohttp.ClientSession,
        request: Request,
        **kwargs,
    ) -> ReturnJson:
        # These queries on their own are unsafe, but we are relying on the safety 
        # checks of the back-end APIs
        if not sql: 
            # Must happen first as we don't know if Carto table is geometric, which 
            # affects geojson SQL query structure
            rv_geom = await self.get_geometry(table, session)  
            if rv_geom and rv_geom.errors: 
                return rv_geom
            
            subq_select = psql.SQL("SELECT objectid AS geojson_id, ")
            geom_column = self.geom_cache[table]['geometry']
            if geom_column:
                if not out_sr: 
                    out_sr = self.DEFAULT_SRID
                subq_select += psql.SQL(
                    "ST_Transform({geom_column}, {out_sr}) AS geojson_shape, "
                ).format(
                    geom_column=psql.Identifier(geom_column),
                    out_sr=psql.Literal(out_sr),
                )
            else: 
                subq_select += psql.SQL("NULL AS geojson_shape, ")
            if fields: 
                field_list = [field.strip() for field in fields.split(",")]
                fields_composed = psql.SQL(', ').join([psql.Identifier(field) for field in field_list])
                fields_composed += psql.SQL(' ')
                subq_select += fields_composed 
            else: 
                subq_select += psql.SQL("* ")

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
        async with session.get(
            self.base_url, params=params, headers=self.auth_header
        ) as response:
            return await self.normalize_rv(request, response, limit, sql)

    async def normalize_rv(
        self,
        request: Request,
        response: aiohttp.ClientResponse,
        limit: int,
        sql: str | None,
    ) -> ReturnJson:
        links = Links(self=str(request.url))
        meta = Meta(service=self.name, service_url=str(response.url))
        if int(response.headers['Content-Length']) >= self.MAX_RESPONSE_SIZE: 
            error = Error(code="413", title="Content Too Large", detail='Request less data; preferably 2,000 rows or fewer.')
            rv = ReturnJson(errors=[error], links=links, meta=meta)
            return rv
        data = await response.json()
        if response.ok: 
            try: 
                records = data["rows"][0]["jsonb_build_object"]
                gjfc = GeoJsonFeatureCollection(**records)
            except KeyError: # When user passed SQL
                geojsons = []
                for record in data['rows']: 
                    geojson = GeoJsonFeature(properties=record)
                    geojsons.append(geojson)
                gjfc = GeoJsonFeatureCollection(features=geojsons)

            meta.record_count = len(gjfc.features)
            if not sql and meta.record_count == limit:
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
