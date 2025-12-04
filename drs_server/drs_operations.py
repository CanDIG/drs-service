import connexion
import drs_database
from flask import Flask, send_file, Response
import requests
import os
import os.path
import re
import authz
from markupsafe import escape
from urllib.parse import parse_qs, urlparse
from time import sleep
from random import randint
from candigv2_logging.logging import CanDIGLogger


logger = CanDIGLogger(__file__)


app = Flask(__name__)

DRS_URL = os.getenv("DRS_URL")


# API endpoints
def get_service_info():
    return {
        "id": "org.candig.drs",
        "name": "CanDIG baby DRS service",
        "type": {
            "group": "org.ga4gh",
            "artifact": "drs",
            "version": "v1.2.0"
        },
        "description": "A DRS-compliant server for CanDIG genomic data",
        "organization": {
            "name": "CanDIG",
            "url": "https://www.distributedgenomics.ca"
        },
        "version": "1.0.0"
    }


@app.route('/ga4gh/drs/v1/objects/<path:object_id>')
def get_object(object_id, expand=False):
    logger.debug(f"looking for object {object_id}")
    access_url_parse = re.match(r"(.+?)/access_url/(.+)", escape(object_id))
    if access_url_parse is not None:
        return get_access_url(access_url_parse.group(1), access_url_parse.group(2))
    new_object = None
    if object_id is not None:
        new_object = drs_database.get_drs_object(escape(object_id), expand)
        auth_code = authz.is_authed(escape(object_id), connexion.request)
        if auth_code != 200:
            return {"message": f"Not authorized to access object {object_id}"}, auth_code
    if new_object is None:
        return {"message": "No matching object found"}, 404
    if "access_methods" in new_object:
        download_method = {
            "access_url": {
                "url": f"{DRS_URL}/ga4gh/drs/v1/objects/{object_id}/download"
            },
            "type": "download"
        }
        new_object["access_methods"].append(download_method)
    return new_object, 200


def get_object_for_drs_uri(drs_uri):
    drs_uri_parse = re.match(r"drs:\/\/(.+)\/(.+)", drs_uri)
    if drs_uri_parse is None:
        return {"message": f"Incorrect format for DRS URI: {drs_uri}"}, 401
    if drs_uri_parse.group(1) in DRS_URL:
        return get_object(drs_uri_parse.group(2))
    return {"message": f"Couldn't resolve DRS server {drs_uri_parse.group(1)}"}, 401


def list_objects(program_id=None, submitter_sample_id=None):
    if program_id is not None:
        if not authz.is_program_authorized(connexion.request, program_id):
            return {"message": f"Not authorized to list objects for program {program_id}"}, 403
    else:
        if not authz.has_full_authz(connexion.request):
            return {"message": f"Not authorized to list all objects"}, 403
    return drs_database.list_drs_objects(program_id=program_id, submitter_sample_id=submitter_sample_id), 200


async def list_experiments():
    if not authz.has_full_authz(connexion.request):
        return {"message": f"Not authorized to list all objects"}, 403
    req = await connexion.request.json()
    result = []

    if "submitter_sample_ids" in req:
        objects = []
        sample_ids = req["submitter_sample_ids"]
        for submitter_sample_id in sample_ids:
            objects.extend(drs_database.list_drs_objects(submitter_sample_id=submitter_sample_id))
    else:
        objects = drs_database.list_drs_objects()
    for object in objects:
        if _is_experiment_object(object):
            result.append(_format_experiment(object))
    return result, 200


@app.route('/ga4gh/drs/v1/objects/<object_id>/access_url/<path:access_id>')
def get_access_url(object_id, access_id, request=connexion.request):
    if object_id is not None:
        auth_code = authz.is_authed(escape(object_id), connexion.request)
        if auth_code != 200:
            return {"message": f"Not authorized to access object {object_id}"}, auth_code
    return _get_access_url(access_id)


@app.route('/ga4gh/drs/v1/objects/<object_id>/download')
def download_file(object_id, request=connexion.request):
    if object_id is not None:
        auth_code = authz.is_authed(escape(object_id), connexion.request)
        if auth_code != 200:
            return {"message": f"Not authorized to access object {object_id}"}, auth_code
    drs_object = drs_database.get_drs_object(escape(object_id))
    if drs_object is None:
        return {"message": f"No object {object_id} was found"}, 404
    if "access_methods" not in drs_object:
        return {"message": f"No files are associated with object {object_id}"}, 404
    if "metadata" in drs_object and drs_object["metadata"] is not None:
        if "analysis_type" in drs_object["metadata"]:
            if drs_object["metadata"]["analysis_type"] == "reference_alignment":
                return {"message": f"Sorry, read files are not allowed to be downloaded"}, 403
    for method in drs_object["access_methods"]:
        if "access_url" in method and method["type"] == "file":
            file_obj = _get_file_path(drs_object["id"])
            return send_file(file_obj["path"]), 200
        elif "access_id" in method:
            url, status_code = _get_access_url(method["access_id"])
            r = requests.get(url["url"], stream=True)
            return Response(r.iter_content(chunk_size=10*1024), content_type=r.headers['Content-Type'])


async def post_object(tries=1):
    req = await connexion.request.json()
    program_id = req["program"]
    object_id = req['id']
    if not authz.is_program_authorized(connexion.request, program_id):
        return {"message": "User is not authorized to POST"}, 403
    if tries > 3:
        raise Exception(f"Exception in post_object {object_id}, too many tries")
    elif tries > 1:
        # if this isn't the first try, pause for a bit and then try again
        sleep(randint(1,10)/2)
    try:
        new_object = drs_database.create_drs_object(req)

        # if this is a file drs object, put the size in
        response = _get_file_path(object_id)
        if response["status_code"] == 200:
            new_object['size'] = response['size']
            new_object = drs_database.create_drs_object(new_object)
    except Exception as e:
        logger.debug(f"Exception in post_object {object_id}: {str(e)}, trying again")
        return post_object(tries=tries+1)
    return new_object, 200


@app.route('/ga4gh/drs/v1/objects/<path:object_id>')
def delete_object(object_id):
    obj = drs_database.get_drs_object(object_id)
    if obj is not None:
        program_id = obj["program"]
        if not authz.is_program_authorized(connexion.request, program_id):
            return {"message": "User is not authorized to POST"}, 403
        try:
            new_object = drs_database.delete_drs_object(escape(object_id))
            return new_object, 200
        except Exception as e:
            return {"message": str(e)}, 500
    else:
        return {"message": f"object {object_id} not found"}, 404


def list_programs():
    programs = drs_database.list_programs()
    if programs is None:
        return [], 404
    try:
        authorized_programs = authz.get_authorized_programs(connexion.request)
        return list(set(map(lambda x: x['id'], programs)).intersection(set(authorized_programs))), 200
    except Exception as e:
        return [], 500


async def post_program():
    req = await connexion.request.json()
    if not authz.is_program_authorized(connexion.request, req['id']):
        return {"message": "User is not authorized to POST"}, 403
    new_program = drs_database.create_program(req)
    return new_program, 200


def get_program(program_id):
    new_program = drs_database.get_program(program_id)
    if new_program is None:
        return {"message": "No matching program found"}, 404
    if authz.is_program_authorized(connexion.request, program_id):
        return new_program, 200
    return {"message": f"Not authorized to access program {program_id}"}, 403


def delete_program(program_id):
    if not authz.is_program_authorized(connexion.request, program_id):
        return {"message": "User is not authorized to POST"}, 403
    try:
        new_program = drs_database.delete_program(program_id)
        return new_program, 200
    except Exception as e:
        return {"message": str(e)}, 500


def get_program_status(program_id):
    new_program = drs_database.get_program(program_id)
    if new_program is None:
        return {"message": "No matching program found"}, 404
    if not authz.is_program_authorized(connexion.request, program_id):
        return {"message": f"Not authorized to access program {program_id}"}, 403

    # get the objects in the program:
    result = {
        "index_complete": [],
        "index_in_progress": [],
        "index_errored": []
    }
    drs_objects = drs_database.list_drs_objects(program_id=program_id)
    for drs_obj in drs_objects:
        drs_uri = drs_obj["self_uri"]
        if "metadata" in drs_obj:
            if "indexed" in drs_obj["metadata"]:
                if drs_obj["metadata"]['indexed'] == 1:
                    result['index_complete'].append(drs_uri)
            if "index_status" in drs_obj["metadata"]:
                status = drs_obj["metadata"]["index_status"]
                if "starting indexing" in status:
                    result['index_in_progress'].append(drs_uri)
                else:
                    result['index_errored'].append(err_obj)
    return result, 200


def _get_file_path(drs_file_obj_id):
    result = { "path": None, "status_code": 200, "method": f"get_file_path({drs_file_obj_id})" }
    drs_file_obj = drs_database.get_drs_object(drs_file_obj_id)
    if drs_file_obj is None:
        result["message"] = f"Couldn't find file {drs_file_obj_id}"
        result['status_code'] = 404
        return result
    # get access_methods for this drs_file_obj
    url = ""
    if "access_methods" not in drs_file_obj:
        result["message"] = f"Object {drs_file_obj_id} is not a file"
        result['status_code'] = 400
        return result
    for method in drs_file_obj["access_methods"]:
        if "access_id" in method and method["access_id"] != "":
            # we need to go to the access endpoint to get the url and file
            (url_obj, status_code) = _get_access_url(method["access_id"])
            result["status_code"] = status_code
            if status_code < 300:
                result["path"] = url_obj["url"]
                result["checksum"] = {
                    "type": "etag",
                    "checksum": url_obj["metadata"].etag
                }
                result["size"] = url_obj["metadata"].size
                break
        elif method["type"] == "file":
            # the access_url has all the info we need
            url_pieces = urlparse(method["access_url"]["url"])
            if url_pieces.scheme == "file":
                if url_pieces.netloc == "" or url_pieces.netloc == "localhost":
                    result["path"] = os.path.abspath(url_pieces.path)
                    if not os.path.exists(result["path"]):
                        result['message'] = f"No file exists at {result['path']} on the server."
                        result['status_code'] = 404
                    else:
                        if len(drs_file_obj["checksums"]) > 0:
                            result["checksum"] = drs_file_obj["checksums"][0]
                        else:
                            result["checksum"] = None
                        result["size"] = os.path.getsize(result["path"])
    if result['path'] is None:
        message = url_obj
        if "error" in url_obj:
            message = url_obj["error"]
        result['message'] = f"No file was found for drs_obj {drs_file_obj_id}: {message}"
        result['status_code'] = 404
        result.pop('path')
    return result


def _get_access_url(access_id):
    logger.debug(f"looking for url {access_id}")
    id_parse = re.match(r"((https*:\/\/)*.+?)\/(.+?)\/(.+?)(\?(.+))*$", access_id)
    if id_parse is not None:
        endpoint = id_parse.group(1)
        bucket = id_parse.group(3)
        object_name = id_parse.group(4)
        url = None
        if id_parse.group(5) is None:
            url, status_code = authz.get_s3_url(s3_endpoint=endpoint, bucket=bucket, object_id=object_name)
        else:
            keys = parse_qs(id_parse.group(6))
            access = None
            secret = None
            public = False
            if 'access' in keys:
                access = keys['access'].pop()
            if 'secret' in keys:
                secret = keys['secret'].pop()
            if 'public' in keys:
                public = True
            url, status_code = authz.get_s3_url(s3_endpoint=endpoint, bucket=bucket, object_id=object_name, access_key=access, secret_key=secret, public=public)
        if status_code == 200:
            return url, status_code
        return url, 500
    else:
        return {"message": f"Malformed access_id {access_id}: should be in the form endpoint/bucket/item", "method": "_get_access_url"}, 400


def _is_experiment_object(drs_object):
    if "access_methods" not in drs_object:
        if drs_object["description"] in ["wgs", "wts"]:
            return True
    return False


def _is_analysis_object(drs_object):
    # This is the bundling object; it has contents referring to the files and experiments. Its unique characteristic is that it has a reference_genome.
    if "access_methods" not in drs_object:
        if "reference_genome" in drs_object:
            return True
    return False


def _is_file_object(drs_object):
    # File objects have access methods.
    if "access_methods" in drs_object:
        return True
    return False


def _format_experiment(experiment_drs_obj):
    result = {
        "experiment_id": experiment_drs_obj["name"],
        "program": experiment_drs_obj["program"],
        "genomes": [],
        "transcriptomes": [],
        "variants": [],
        "reads": [],
        "expressions": []
    }

    if _is_experiment_object(experiment_drs_obj):
        if experiment_drs_obj["description"] == "wgs":
            result["genomes"].append(experiment_drs_obj["id"])
        elif experiment_drs_obj["description"] == "wts":
            result["transcriptomes"].append(experiment_drs_obj["id"])
        analysis_contents = drs_database.get_contents_for_drs_obj(experiment_drs_obj["id"])
        if len(analysis_contents) > 0:
            for analysis in analysis_contents:
                # get the analysis object
                analysis_obj = drs_database.get_drs_object(analysis["id"])
                if analysis_obj["description"] == "sequence_variation":
                    result["variants"].append(analysis_obj["name"])
                elif analysis_obj["description"] == "reference_alignment":
                    result["reads"].append(analysis_obj["name"])
                elif analysis_obj["description"] == "sequence_annotation":
                    result["expressions"].append(analysis_obj["name"])
        return result
    return None
