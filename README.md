# OIT API Wrapper
**_Author: James Midkiff_**

Read the API docs at `<api_endpoint>/docs`

For local development and testing, copy `env.example` to `.env` and populate it. Then run `export $(grep -v '^#' .env | xargs)` to export them as environment variables so the python program can access it.

Running the API locally:

`uvicorn app.main:app --reload --host 0.0.0.0 --port 8000`

To run in a docker container, make sure your .env file is setup then run:

`docker-compose up --build -d`

Testing:

`pytest`