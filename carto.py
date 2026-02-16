from abstract_worker import AbstractWorker, ReturnJson, Meta, Links, Error, GeoJsonFeatureCollection, GeoJsonFeature
import aiohttp
import json
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
                subq_select = psql.SQL('SELECT ST_Transform(the_geom, 4326), ')
                field_list = [field.strip() for field in fields.split(",")]
                fields_composed = psql.SQL(', ').join([psql.Identifier(field) for field in field_list])
                fields_composed += (psql.SQL(' '))
                subq_select += fields_composed 
            else: 
                subq_select = psql.SQL("SELECT ST_Transform(the_geom, 4326), * ")

            subq_from = psql.SQL('FROM {table} ').format(table=psql.Identifier(table))
            subq = subq_select + subq_from
            if where: 
                subq_where = psql.SQL(f'WHERE {where} ')
                subq = subq + subq_where
            subq += psql.SQL('ORDER BY cartodb_id ')
            if limit is None: 
                limit = self.MAX_RECORDS
            else: 
                limit = min(limit, self.MAX_RECORDS)
            subq_limit = psql.SQL('LIMIT {limit} ').format(limit=psql.Literal(limit))
            subq = subq + subq_limit
            query = psql.SQL('WITH subq as ({subq}) SELECT ST_AsGeoJSON(subq.*) FROM subq').format(subq=subq)
        else: 
            query = psql.SQL(sql)
        params = {'q': query.as_string()}
        async with session.get(self.base_url, params=params) as response:
            return await self.normalize_rv(request, response, limit)

    async def normalize_rv(
        self, request: Request, response: aiohttp.ClientResponse, limit: int
    ) -> ReturnJson:
        links = Links(self=str(request.url))
        meta = Meta(service=self.name, service_url=str(response.url))
        data = await response.json()
        if response.ok: 
            records = data['rows']
            meta.record_count = data['total_rows']
            if meta.record_count == limit:
                next_url = self.create_next_url(records, request)
                links.next = next_url
            gjfc = self.create_geojson_feature_collection(records)
            rv = ReturnJson(data=gjfc, links=links, meta=meta)
            return rv
        else: 
            error = Error(
                code=response.status,
                title=f"{self.name} Error",
                detail=data["error"][0],
            )
            rv = ReturnJson(errors=[error], links=links, meta=meta)
            return rv

    def create_next_where_clause(self, data: list[dict]) -> str:
        """Create the WHERE clause to be used in the NEXT url link to retrieve 
        the next set of data. Implementation is API-specific

        Args:
            data (list[dict]): Data records

        Returns:
            str: WHERE clause restricting the data to be retrieved
        """        
        max_objectid = self.get_data_max_objectid(data, ["cartodb_id"])
        next_where = f"cartodb_id > {max_objectid}"
        return next_where

    def create_geojson_feature_collection(
        self, records: list[dict]
    ) -> GeoJsonFeatureCollection:
        geojsons = []
        for record in records: 
            j = json.loads(record['st_asgeojson'])
            geojson = GeoJsonFeature(**j)
            geojsons.append(geojson)
        gjfc = GeoJsonFeatureCollection(features=geojsons)
        return gjfc
