import configparser
import os
import re

config = configparser.ConfigParser(interpolation=None)
config.read(os.path.abspath(f"{os.path.dirname(os.path.realpath(__file__))}/../config.ini"))

AUTHZ = config['authz']

if os.environ.get("PGPASSWORD") is not None:
    password = os.environ.get("PGPASSWORD")
elif os.environ.get("POSTGRES_PASSWORD_FILE") is not None and os.path.exists(os.environ.get("POSTGRES_PASSWORD_FILE")):
    with open(os.environ.get("POSTGRES_PASSWORD_FILE"), 'r') as file:
        password = file.read()
else:
    raise Exception("Could not determine how to get PostGres password")

DRS_DB_PATH = re.sub("PASSWORD", password, config['paths']['DRSPath'])
DRS_DB_PATH = re.sub("HOST", os.environ.get("DB_PATH"), DRS_DB_PATH)

PORT = config['DEFAULT']['Port']

MAX_TRIES = int(config['DEFAULT']['MaxTries'])

TEST_KEY = os.getenv("HTSGET_TEST_KEY", "testtesttest")

DEBUG_MODE = False
if os.getenv("DEBUG_MODE", "1") == "1":
    DEBUG_MODE = True
