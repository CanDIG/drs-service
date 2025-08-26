ARG venv_python=3.12
FROM python:${venv_python}

LABEL Maintainer="CanDIG Project"
LABEL "candigv2"="drs_app"

USER root

RUN groupadd -r candig && useradd -rm candig -g candig

RUN apt-get update && apt-get -y install \
	cron \
	postgresql-client \
    postgresql

COPY requirements.txt /app/drs_server/requirements.txt

RUN pip install --no-cache-dir -r /app/drs_server/requirements.txt

COPY . /app/drs_server

WORKDIR /app/drs_server

RUN chown -R candig:candig /app/drs_server

USER candig

RUN touch initial_setup

ENTRYPOINT ["bash", "entrypoint.sh"]
