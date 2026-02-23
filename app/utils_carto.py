FULL_QUERY = """
WITH subq as (
    {subq}
),
geojson as (
    SELECT
        (
            ST_AsGeoJSON(
                subq.*,
                geom_column => 'geojson_shape',
                id_column => 'geojson_id'
            ) :: jsonb
        ) AS feature
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