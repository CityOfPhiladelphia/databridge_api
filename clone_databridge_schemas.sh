#!/bin/bash

KEY_FILE="~/.ssh/oit_api_wrapper_key"
FILE_PATH="./databridge-schemas"

if test -d $FILE_PATH; then 
    cd $FILE_PATH &&
    GIT_SSH_COMMAND="ssh -i \"$KEY_FILE\"" git pull git@github.com:CityOfPhiladelphia/databridge-schemas.git;
else 
    GIT_SSH_COMMAND="ssh -i \"$KEY_FILE\"" git clone git@github.com:CityOfPhiladelphia/databridge-schemas.git;
fi
