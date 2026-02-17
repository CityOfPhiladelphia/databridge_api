FULL_QUERY = """
WITH subq as (
    {subq}
),
geojson as (
    SELECT
        (ST_AsGeoJSON(subq.*, geom_column => 'shape_1984', id_column => 'objectid') :: jsonb) AS feature
    FROM
        subq
)
SELECT
    jsonb_build_object(
        'type',
        'FeatureCollection',
        'features',
        COALESCE(jsonb_agg(geojson.feature), '[]' :: jsonb)
    )
FROM
    geojson
"""