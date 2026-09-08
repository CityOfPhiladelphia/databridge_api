# Databridge API
**_Author: James Midkiff_**

Read the API docs at `<api_endpoint>/api/docs`

The publicly accessible endpoints are actually at the path `/api`, i.e. the standard 
`GET` request goes to `/api/get`, but this is hidden from the user by the reverse proxy, Mulesoft.

### APIs
This API interfaces with the following APIs: 
* PostgREST
    * This API connects to `databridge-public` and reads PostgreSQL functions unique to each table there
    * These functions are created via an [Airflow task](https://github.com/CityOfPhiladelphia/airflow-iac-dags/edit/main/lib/databridge_tasks/upload_to_db_public_simple.py)
* ArcGIS Online
* CARTO V3


### Debugging
There is an internal endpoint available for testing. This will only be accessible on the City network, i.e. not by the reverse proxy. 

It's available at `/schemas`, and you can pass `?table=<table>` to see a specific table's schema

### Development

For local development and testing, copy `env.example` to `.env` and populate it. Then run `export $(grep -v '^#' .env | xargs)` to export them as environment variables so the python program can access it.

Running the API locally:

`uv run fastapi --env-file=.env fastapi dev`

To run in a docker container, make sure your .env file is setup then run:

`docker-compose up --build -d`

### Testing

`uv run --env-file=.env pytest --maxfail=4 --tb=short -v`