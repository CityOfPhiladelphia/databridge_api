import requests


TIMEOUT = 15
AGO_SECRET = "AGO/maps.phl.data"


def generate_ago_token(creds: dict) -> dict:
    """Generate an access token in exchange for user credentials that can be 
    used by clients when working with the ArcGIS Portal API:
    https://developers.arcgis.com/rest/users-groups-and-items/generate-token/
    
    Args:
        creds (dict): Login credentials

    Returns:
        str: Token
    """    
    # Assume first item passed to us is the user specific creds
    first = next(iter(creds))
    login_creds = creds[first]
    user = login_creds['login']
    password = login_creds['password']
    url = login_creds['url'] + "/sharing/rest/generateToken"
    data = {'username': user,
            'password': password,
            'referer': login_creds['url'],
            'f': 'json'}
    print('Requesting AGO token')
    response = requests.post(url, data, timeout=TIMEOUT)
    check_ago_errors(response)
    return response.json()


def check_ago_errors(response: requests.Response):
    """Parse the AGO response object and raise any errors found. Errors are raised
    as if they were a `requests.HTTPError`

    Args:
        response (requests.Response): A response coming from AGO

    Raises:
        requests.HTTPError: Either a true HTTPError or an AGO Response Error
    """
    response.raise_for_status()
    json_response = response.json()
    if "error" in json_response:  # This structure is used for AGO token
        e = requests.HTTPError(
            json_response["error"]["code"], json_response["error"]["message"]
        )
        s = "\n".join(json_response["error"]["details"])
        e.add_note(s)
        raise e
    if (len(json_response.keys()) == 1):  # This structure is used for Add / Update / Delete Features
        rvs = json_response[list(json_response.keys())[0]]
        for rv in rvs:
            if "error" in rv:
                e = requests.HTTPError(rv["error"]["code"], rv["error"]["description"])
                raise e
