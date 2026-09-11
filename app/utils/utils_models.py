import tomllib
from pathlib import Path


def retrieve_app_version() -> str: 
    """Retrieve the version of this API from the pyprject.toml file

    Returns:
        str: API version
    """    
    file_path = Path.cwd() / 'pyproject.toml'
    assert file_path.is_file()
    with open(file_path, mode='rb') as f: 
        toml = tomllib.load(f)
        version = toml['project']['version']

    return version 


app_version = retrieve_app_version()
