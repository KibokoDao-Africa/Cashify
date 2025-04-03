# use this image as the base
FROM python:3.13-slim

# create a working directory in the container and cd into it
WORKDIR /bot

# copy and install dependencies to working directory
COPY requirements.txt requirements.txt
RUN pip3 install -r requirements.txt

# copy source code to working directory
COPY . .
