import json
import sys
from ast import literal_eval

DEFAULT_FORMAT = {
    "openapi": "3.0.0",
    "info": {
        "title": "",
        "description": "",
        "version": "1.0"
    },
    "servers": [],
    "paths": {},
    "security": [{"ApiKeyAuth": []}],
    "components": {"securitySchemes": {"ApiKeyAuth": {"type": "apiKey", "in": "header", "name": "secret"}}}
}

CONSUMES = [
    "application/json"
]

DATA_TYPES = {
    int: 'integer',
    str: 'string',
    dict: 'object',
    list: 'array',
    type(None): 'string'
}


def _add_server(path_prefix, env_variables):
    import re

    path_prefix = path_prefix.format()
    var_list = re.findall(r'{(.+?)}', path_prefix)
    variables = {}
    for v in var_list:
        if env_variables.get(v, None):
            path_prefix = path_prefix.replace("{"+v+"}", env_variables.get(v))
        else:
            variables[v] = {"default": env_variables.get(v, "-")}
    DEFAULT_FORMAT['servers'].append({
        "url": path_prefix if path_prefix.startswith("http") else "http://" + path_prefix,
        "variables": variables
    }
    )


def _get_prefix(m):
    if not m:
        return ''
    s1 = min(m)
    s2 = max(m)
    for i, c in enumerate(s1):
        if c != s2[i]:
            return s1[:i]
    return s1


def _read_description(desc):
    if desc:
        try:
            return dict((k, literal_eval(v)) for k, v in (pair.strip().split('=') for pair in desc.split("|")))
        except Exception as e:
            print(e, desc)
            pass
    return {'description': desc}


def _read_list(data_list):
    items = {}
    if data_list:
        item_type = DATA_TYPES[type(data_list[0])]
        if isinstance(data_list[0], dict):
            items = _read_dict(data_list[0])
        else:
            items = {'type': item_type}
    return {'type': DATA_TYPES[list], 'items': items}


def _read_dict(data_dict):
    new_dict = {}
    for k, v in data_dict.items():
        if isinstance(v, dict):
            new_dict[k] = _read_dict(v)
        elif isinstance(v, list):
            new_dict[k] = _read_list(v)
        else:
            new_dict[k] = {
                "type": DATA_TYPES[type(v)]
            }
    return {'type': DATA_TYPES[dict], 'properties': new_dict}


def _format_form_data(body):
    schema = {"required": [], "type": "object", "properties": {}}
    for item in body:
        schema['required'].append(item['key'])
        schema['properties'][item['key']] = {"type": "string"}
    return {"application/x-www-form-urlencoded": {"schema": schema}}


def get_body(request):
    resp_data = {}
    if request:
        body = request.get('body', None)
        content = next((i['value'] for i in request['header'] if i['key'] == 'Content-Type'), None)
        if content and body and body[body['mode']]:
            # resp_data['description'] = "{0} with response code {1}".format(request['name'], request['code'])
            resp_data['required'] = True
            if body['mode'] == 'formdata':
                resp_data['content'] = _format_form_data(body[body['mode']])
                print(body)
            else:
                body_json = json.loads(body[body['mode']])
                resp_data['content'] = {content: _format_body_schema(body_json)}
    return resp_data


def get_response(response):
    resp_data = {}

    if response:
        for resp in response:
            body = resp.get('body', None)
            resp_dict = {}
            content = next((i['value'] for i in resp['header'] if i['key'] == 'Content-Type'), None)
            if content and body:
                resp_dict['description'] = resp['name']
                body_json = json.loads(body)
                resp_dict['content'] = {content: _format_body_schema(body_json)}
                resp_data[resp['code']] = resp_dict
        return resp_data
    return {'999': {'description': "RESPONSE NOT PROVIDED"}}


def _format_body_schema(body):
    body_data = {}
    if isinstance(body, list):
        body_data = _read_list(body)
        body_data['example'] = body
    elif isinstance(body, dict):
        body_data = _read_dict(body)
        body_data['example'] = body
    return {"schema": body_data, 'example': body}


def get_path_list(postman_data):
    paths = []
    for itm_data in postman_data:
        if itm_data.get('request', None):
            actual_path = itm_data['request']['url']['raw']
            paths.append(actual_path)
        if itm_data.get('item', None):
            paths += get_path_list(itm_data['item'])
    return list(set(paths))


def process_headers(headers):
    return_list = []
    for header in headers:
        if header['key'] not in ["Content-Type"]:
            h_dict = {
                "name": header['key'],
                "in": "header",
                "required": True,
                "style": "simple",
                "explode": False,
                "schema": {
                    "type": "string",
                    "example": header['value'] if header['value'] != '{{secret_key}}' else ""
                },
                "description": header.get('description', '')
            }

            h_dict = _get_user_params(header.get('description', ''), h_dict)

            return_list.append(h_dict)
    return return_list


def _get_user_params(desc, item):
    desc_data = _read_description(desc)
    for k, v in desc_data.items():
        if k in ["enum", 'type', 'example']:
            item['schema'][k] = v
        else:
            item[k] = v
    return item


def process_query_params(query_params):
    return_list = []
    for param in query_params:
        i = {
            "name": param['key'],
            "in": "query",
            "required": False,
            "schema": {
                "type": "string",
                "example": param['value'] if param['value'] != '{{secret_key}}' else "",
            },
            "description": ""
        }
        i = _get_user_params(param.get('description', ''), i)
        return_list.append(i)
    return return_list


def process_path_variables(path):
    assert path is not None
    return []


def convert_to_swagger(path_details, tag, prefix):
    request = path_details['request']
    name = path_details['name']
    parameters = []
    path = request['url']['raw']
    method = request['method'].lower()

    path = path.replace(prefix, "/")
    path = path.split("?")[0]
    parameters += process_headers(request['header'])
    parameters += process_path_variables(path)
    parameters += process_query_params(request['url'].get('query', []))
    path_data = {
        "tags": [tag],
        'operationId': "{}_{}-{}".format(method.lower(), tag, "-".join(name.lower().split(' '))),
        'summary': name,
        'parameters': parameters,
        'responses': get_response(path_details['response'])

    }
    if method in ['put', 'post']:
        body = get_body(request)
        if body:
            path_data['requestBody'] = body
    try:
        DEFAULT_FORMAT['paths'][path][method] = path_data
    except KeyError:
        DEFAULT_FORMAT['paths'][path] = {method: path_data}


def process(req_list, tag, prefix):
    for r in req_list:
        if r.get('request', None):
            convert_to_swagger(r, tag, prefix)
        elif r.get('item', None):
            process(r['item'], tag, prefix)


def main(args):

    if len(args) < 1:
        raise EOFError('Please pass file name')
    file = args.pop(0)
    data = json.load(open(file, 'r'))

    env_variables = dict(("{0}".format(k), v) for k, v in (pair.split('=') for pair in args))
    paths_list = get_path_list(data['item'])
    prefix = _get_prefix(paths_list)
    _add_server(prefix, env_variables)
    DEFAULT_FORMAT['info']['title'] = data['info']['name']
    for sub_divisions in data['item']:
        tag = sub_divisions['name']
        process(sub_divisions['item'], tag, prefix)

    new_path = {}
    for key in sorted(list(DEFAULT_FORMAT['paths'].keys())):
        new_path[key] = DEFAULT_FORMAT['paths'][key]

    DEFAULT_FORMAT['paths'] = new_path

    with open('test_site/swagger.json', 'w+') as fp:
        json.dump(DEFAULT_FORMAT, fp, indent=4)


if __name__ == "__main__":
    main(sys.argv[1:])
