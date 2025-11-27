import json
import os
import re
import sys
import pytest
import requests
from pathlib import Path
from authx.auth import get_site_admin_token, store_aws_credential
from time import sleep

# assumes that we are running pytest from the repo directory
REPO_DIR = os.path.abspath(f"{os.path.dirname(os.path.realpath(__file__))}/..")
sys.path.insert(0, os.path.abspath(f"{REPO_DIR}/htsget_server"))
LOCAL_FILE_PATH = os.path.abspath(f"{REPO_DIR}/data/files")
SERVER_LOCAL_DATA = os.getenv("SERVER_LOCAL_DATA", "/app/htsget_server/data")

HOST = os.getenv("TESTENV_URL")
TEST_KEY = os.getenv("HTSGET_TEST_KEY")
USERNAME = os.getenv("CANDIG_NOT_ADMIN_USER2", "user2@test.ca")
DRS_URL = os.getenv("DRS_PRIVATE_URL")
MINIO_URL = os.getenv("MINIO_URL")
VAULT_URL = os.getenv("VAULT_URL")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY")
CWD = os.getcwd()


def get_headers():
    headers = {}
    if TEST_KEY is not None:
        headers["Authorization"] = f"Bearer {TEST_KEY}"
        return headers
    try:
        token = get_site_admin_token()
        headers["Authorization"] = f"Bearer {token}"
    except Exception as e:
        headers["Authorization"] = f"Bearer {TEST_KEY}"
    return headers


def remove_programs(programs):
    headers = get_headers()
    candig_url = os.getenv("CANDIG_URL")

    for program in programs:
        if candig_url is not None:
            response = requests.delete(f"{candig_url}/ingest/program/{program}", headers=get_headers())

        url = f"{DRS_URL}/ga4gh/drs/v1/programs/{program}"
        response = requests.request("GET", url, headers=headers)
        if response.status_code == 200:
            response = requests.request("DELETE", url, headers=headers)
            print(f"DELETE {program}: {response.text}")
            assert response.status_code == 200
        url = f"{DRS_URL}/ga4gh/drs/v1/objects"
        response = requests.request("GET", url, headers=headers, params={"program_id": program})
        print(response.text)
        assert response.status_code == 200
        for obj in response.json():
            assert obj["program"] != program


def test_post_objects(drs_objects, programs):
    """
    Install test objects. Will fail if any post request returns an error.
    """
    # clean up old objects in db:
    remove_programs(programs)

    url = f"{DRS_URL}/ga4gh/drs/v1/objects"
    headers = get_headers()
    candig_url = os.getenv("CANDIG_URL")

    for program in programs:
        if candig_url is not None:
            test_program = {
                "program_id": program,
                "program_curators": [USERNAME],
                "team_members": [USERNAME]
            }

            response = requests.post(f"{candig_url}/ingest/program", headers=get_headers(), json=test_program)
            print(response.text)

    response = requests.request("GET", url, headers=headers)
    for obj in drs_objects:
        url = f"{DRS_URL}/ga4gh/drs/v1/objects"
        response = requests.request("POST", url, json=obj, headers=headers)
        print(f"POST {obj}: {response.text}")
        assert response.status_code == 200


def get_ingest_file():
    return [
        (
            {
                "program_id": "1000genomes",
                "experiment_id": "LOCAL-SEQ_0090",
                "submitter_sample_id": "NA18537-wgs",
                "metadata": {
                    "library_strategy": "WGS"
                }
            },
            {
                "program_id": "1000genomes",
                "analysis_id": "NA18537",
                "analysis_sample_id": "NA18537",
                "experiment_id": "NA18537-wgs"
            }
        )
    ]


def get_ingest_experiment_names(genomic_id):
    result = {}
    for item in get_ingest_file():
        ingest_map, program_id = item
        if ingest_map["genomic_id"] == genomic_id:
            for sample in ingest_map["samples"]:
                result[sample['sample_registration_id']] = f"{sample['sample_name_in_file']}"
    return result


@pytest.mark.parametrize('experiment, analysis', get_ingest_file())
def test_add_experiment_drs(experiment, analysis):
    post_url = f"{DRS_URL}/ga4gh/drs/v1/objects"
    headers = get_headers()

    # look for the main analysis drs object
    get_url = f"{DRS_URL}/ga4gh/drs/v1/objects/{analysis['analysis_id']}"
    response = requests.request("GET", get_url, headers=headers)
    if response.status_code == 200:
        assert response.status_code == 200
    analysis_drs_obj = response.json()
    contents_count = len(analysis_drs_obj["contents"])

    drs_url = HOST.replace("http://", "drs://").replace("https://", "drs://")

    # create a experimentdrsobject to correspond to each experiment:
    experiment_drs_object = {
        "id": experiment['experiment_id'],
        "name": experiment["submitter_sample_id"],
        "description": "wgs",
        "program": experiment['program_id'],
        "contents": [
            {
                "drs_uri": [
                    f"{drs_url}/{analysis['analysis_id']}"
                ],
                "name": analysis['analysis_sample_id'],
                "id": analysis['analysis_id']
            }
        ],
        "version": "v1",
        "metadata": {}
    }
    response = requests.request("POST", post_url, json=experiment_drs_object, headers=headers)
    print(f"POST {experiment_drs_object['id']}: {response.text}")
    assert response.status_code == 200

    # add the experiment contents to the analysis_drs_object's contents
    experiment_contents = {
        "drs_uri": [
            f"{drs_url}/{experiment['experiment_id']}"
        ],
        "name": experiment['experiment_id'],
        "id": analysis['analysis_sample_id']
    }
    analysis_drs_obj["contents"].append(experiment_contents)

    response = requests.post(post_url, json=analysis_drs_obj, headers=get_headers())
    print(response.text)
    response = requests.request("GET", get_url, headers=get_headers())
    if response.status_code == 200:
        assert response.status_code == 200
    assert len(analysis_drs_obj["contents"]) == contents_count + 1


@pytest.fixture
def programs():
    return ["test-htsget", "1000genomes"]


@pytest.fixture
def drs_objects():
    return [
      {
        "id": "multisample_2",
        "description": "analysis",
        "mime_type": "application/octet-stream",
        "name": "multisample_2",
        "contents": [
          {
            "drs_uri": [
              "drs://htsget:3000/multisample_2.vcf.gz.tbi"
            ],
            "name": "multisample_2.vcf.gz.tbi",
            "id": "index"
          },
          {
            "drs_uri": [
              "drs://htsget:3000/multisample_2.vcf.gz"
            ],
            "name": "multisample_2.vcf.gz",
            "id": "variant"
          }
        ],
        "version": "v1",
        "reference_genome": "hg38",
        "program": "test-htsget"
      },
      {
        "id": "multisample_2.vcf.gz.tbi",
        "description": "index",
        "mime_type": "application/octet-stream",
        "name": "multisample_2.vcf.gz.tbi",
        "version": "v1",
        "program": "test-htsget",
        "access_methods": [
          {
            "type": "file",
            "access_url": {
              "url": "file:////app/htsget_server/data/files/multisample_2.vcf.gz.tbi"
            }
          }
        ]
      },
      {
        "id": "multisample_2.vcf.gz",
        "description": "analysis",
        "mime_type": "application/octet-stream",
        "name": "multisample_2.vcf.gz",
        "version": "v1",
        "program": "test-htsget",
        "access_methods": [
          {
            "type": "file",
            "access_url": {
              "url": "file:////app/htsget_server/data/files/multisample_2.vcf.gz"
            }
          }
        ]
      },
      {
        "id": "sample.compressed",
        "description": "analysis",
        "mime_type": "application/octet-stream",
        "name": "sample.compressed",
        "contents": [
          {
            "drs_uri": [
              "drs://htsget:3000/sample.compressed.vcf.gz.tbi"
            ],
            "name": "sample.compressed.vcf.gz.tbi",
            "id": "index"
          },
          {
            "drs_uri": [
              "drs://htsget:3000/sample.compressed.vcf.gz"
            ],
            "name": "sample.compressed.vcf.gz",
            "id": "variant"
          }
        ],
        "version": "v1",
        "reference_genome": "hg38",
        "program": "test-htsget"
      },
      {
        "id": "sample.compressed.vcf.gz.tbi",
        "description": "index",
        "mime_type": "application/octet-stream",
        "name": "sample.compressed.vcf.gz.tbi",
        "version": "v1",
        "program": "test-htsget",
        "access_methods": [
          {
            "type": "file",
            "access_url": {
              "url": "file:////app/htsget_server/data/files/sample.compressed.vcf.gz.tbi"
            }
          }
        ]
      },
      {
        "id": "sample.compressed.vcf.gz",
        "description": "analysis",
        "mime_type": "application/octet-stream",
        "name": "sample.compressed.vcf.gz",
        "version": "v1",
        "program": "test-htsget",
        "access_methods": [
          {
            "type": "file",
            "access_url": {
              "url": "file:////app/htsget_server/data/files/sample.compressed.vcf.gz"
            }
          }
        ]
      },
      {
        "id": "NA20787",
        "description": "analysis",
        "mime_type": "application/octet-stream",
        "name": "NA20787",
        "contents": [
          {
            "drs_uri": [
              "drs://htsget:3000/NA20787.vcf.gz.tbi"
            ],
            "name": "NA20787.vcf.gz.tbi",
            "id": "index"
          },
          {
            "drs_uri": [
              "drs://htsget:3000/NA20787.vcf.gz"
            ],
            "name": "NA20787.vcf.gz",
            "id": "variant"
          }
        ],
        "version": "v1",
        "reference_genome": "hg38",
        "program": "test-htsget"
      },
      {
        "id": "NA20787.vcf.gz.tbi",
        "description": "index",
        "mime_type": "application/octet-stream",
        "name": "NA20787.vcf.gz.tbi",
        "version": "v1",
        "program": "test-htsget",
        "access_methods": [
          {
            "type": "file",
            "access_url": {
              "url": "file:////app/htsget_server/data/files/NA20787.vcf.gz.tbi"
            }
          }
        ]
      },
      {
        "id": "NA20787.vcf.gz",
        "description": "analysis",
        "mime_type": "application/octet-stream",
        "name": "NA20787.vcf.gz",
        "version": "v1",
        "program": "test-htsget",
        "access_methods": [
          {
            "type": "file",
            "access_url": {
              "url": "file:////app/htsget_server/data/files/NA20787.vcf.gz"
            }
          }
        ]
      },
      {
        "id": "multisample_1",
        "description": "analysis",
        "mime_type": "application/octet-stream",
        "name": "multisample_1",
        "contents": [
          {
            "drs_uri": [
              "drs://htsget:3000/multisample_1.vcf.gz.tbi"
            ],
            "name": "multisample_1.vcf.gz.tbi",
            "id": "index"
          },
          {
            "drs_uri": [
              "drs://htsget:3000/multisample_1.vcf.gz"
            ],
            "name": "multisample_1.vcf.gz",
            "id": "variant"
          }
        ],
        "version": "v1",
        "reference_genome": "hg38",
        "program": "test-htsget"
      },
      {
        "id": "multisample_1.vcf.gz.tbi",
        "description": "index",
        "mime_type": "application/octet-stream",
        "name": "multisample_1.vcf.gz.tbi",
        "version": "v1",
        "program": "test-htsget",
        "access_methods": [
          {
            "type": "file",
            "access_url": {
              "url": "file:////app/htsget_server/data/files/multisample_1.vcf.gz.tbi"
            }
          }
        ]
      },
      {
        "id": "multisample_1.vcf.gz",
        "description": "analysis",
        "mime_type": "application/octet-stream",
        "name": "multisample_1.vcf.gz",
        "version": "v1",
        "program": "test-htsget",
        "access_methods": [
          {
            "type": "file",
            "access_url": {
              "url": "file:////app/htsget_server/data/files/multisample_1.vcf.gz"
            }
          }
        ]
      },
      {
        "id": "test",
        "description": "analysis",
        "mime_type": "application/octet-stream",
        "name": "test",
        "contents": [
          {
            "drs_uri": [
              "drs://htsget:3000/test.vcf.gz.tbi"
            ],
            "name": "test.vcf.gz.tbi",
            "id": "index"
          },
          {
            "drs_uri": [
              "drs://htsget:3000/test.vcf.gz"
            ],
            "name": "test.vcf.gz",
            "id": "variant"
          }
        ],
        "version": "v1",
        "reference_genome": "hg38",
        "program": "test-htsget"
      },
      {
        "id": "test.vcf.gz.tbi",
        "description": "index",
        "mime_type": "application/octet-stream",
        "name": "test.vcf.gz.tbi",
        "version": "v1",
        "program": "test-htsget",
        "access_methods": [
          {
            "type": "file",
            "access_url": {
              "url": "file:////app/htsget_server/data/files/test.vcf.gz.tbi"
            }
          }
        ]
      },
      {
        "id": "test.vcf.gz",
        "description": "analysis",
        "mime_type": "application/octet-stream",
        "name": "test.vcf.gz",
        "version": "v1",
        "program": "test-htsget",
        "access_methods": [
          {
            "type": "file",
            "access_url": {
              "url": "file:////app/htsget_server/data/files/test.vcf.gz"
            }
          }
        ]
      },
      {
        "id": "NA18537",
        "description": "analysis",
        "mime_type": "application/octet-stream",
        "name": "NA18537",
        "contents": [
          {
            "drs_uri": [
              "drs://htsget:3000/NA18537.vcf.gz.tbi"
            ],
            "name": "NA18537.vcf.gz.tbi",
            "id": "index"
          },
          {
            "drs_uri": [
              "drs://htsget:3000/NA18537.vcf.gz"
            ],
            "name": "NA18537.vcf.gz",
            "id": "variant"
          }
        ],
        "version": "v1",
        "reference_genome": "hg38",
        "program": "test-htsget"
      },
      {
        "id": "NA18537.vcf.gz.tbi",
        "description": "index",
        "mime_type": "application/octet-stream",
        "name": "NA18537.vcf.gz.tbi",
        "version": "v1",
        "program": "test-htsget",
        "access_methods": [
          {
            "type": "file",
            "access_url": {
              "url": "file:////app/htsget_server/data/files/NA18537.vcf.gz.tbi"
            }
          }
        ]
      },
      {
        "id": "NA18537.vcf.gz",
        "description": "analysis",
        "mime_type": "application/octet-stream",
        "name": "NA18537.vcf.gz",
        "version": "v1",
        "program": "test-htsget",
        "access_methods": [
          {
            "type": "file",
            "access_url": {
              "url": "file:////app/htsget_server/data/files/NA18537.vcf.gz"
            }
          }
        ]
      },
      {
        "id": "HG02102",
        "description": "analysis",
        "mime_type": "application/octet-stream",
        "name": "HG02102",
        "contents": [
          {
            "drs_uri": [
              "drs://htsget:3000/HG02102.vcf.gz.tbi"
            ],
            "name": "HG02102.vcf.gz.tbi",
            "id": "index"
          },
          {
            "drs_uri": [
              "drs://htsget:3000/HG02102.vcf.gz"
            ],
            "name": "HG02102.vcf.gz",
            "id": "variant"
          }
        ],
        "version": "v1",
        "reference_genome": "hg38",
        "program": "test-htsget"
      },
      {
        "id": "HG02102.vcf.gz.tbi",
        "description": "index",
        "mime_type": "application/octet-stream",
        "name": "HG02102.vcf.gz.tbi",
        "version": "v1",
        "program": "test-htsget",
        "access_methods": [
          {
            "type": "file",
            "access_url": {
              "url": "file:////app/htsget_server/data/files/HG02102.vcf.gz.tbi"
            }
          }
        ]
      },
      {
        "id": "HG02102.vcf.gz",
        "description": "analysis",
        "mime_type": "application/octet-stream",
        "name": "HG02102.vcf.gz",
        "version": "v1",
        "program": "test-htsget",
        "access_methods": [
          {
            "type": "file",
            "access_url": {
              "url": "file:////app/htsget_server/data/files/HG02102.vcf.gz"
            }
          }
        ]
      },
      {
        "id": "NA02102",
        "description": "analysis",
        "mime_type": "application/octet-stream",
        "name": "NA02102",
        "contents": [
          {
            "drs_uri": [
              "drs://htsget:3000/NA02102.bam.bai"
            ],
            "name": "NA02102.bam.bai",
            "id": "index"
          },
          {
            "drs_uri": [
              "drs://htsget:3000/NA02102.bam"
            ],
            "name": "NA02102.bam",
            "id": "read"
          }
        ],
        "version": "v1",
        "reference_genome": "hg38",
        "program": "test-htsget"
      },
      {
        "id": "NA02102.bam.bai",
        "description": "index",
        "mime_type": "application/octet-stream",
        "name": "NA02102.bam.bai",
        "version": "v1",
        "program": "test-htsget",
        "access_methods": [
          {
            "type": "file",
            "access_url": {
              "url": "file:////app/htsget_server/data/files/NA02102.bam.bai"
            }
          }
        ]
      },
      {
        "id": "NA02102.bam",
        "description": "analysis",
        "mime_type": "application/octet-stream",
        "name": "NA02102.bam",
        "version": "v1",
        "program": "test-htsget",
        "access_methods": [
          {
            "type": "file",
            "access_url": {
              "url": "file:////app/htsget_server/data/files/NA02102.bam"
            }
          }
        ]
      }
    ]
