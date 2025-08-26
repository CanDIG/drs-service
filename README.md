# DRS Application

DRS-compliant API implementation that allows access to data objects. The [OpenAPI file](drs_server/drs_openapi.yml) specifies a suggested format for DRS-compliant genomic data objects.

## Stack
- [Connexion](https://github.com/zalando/connexion) for implementing the API
- [PostgreSQL](https://www.postgresql.org/)
- [ga4gh Data-Repository-Service(DRS)](https://github.com/ga4gh/data-repository-service-schemas)
- [Flask](http://flask.pocoo.org/)
- Python 3
- Pytest

## Installation

The server is meant to be run in the context of the [CanDIG stack](https://candig.github.io/CanDIGv2/deployment/local/).

## Testing

An automated test suite is provided, but can only be run in the docker container stack context. If you are running the CanDIG stack, you can run the tests with
```
docker exec candigv2_drs_1 pytest
```
