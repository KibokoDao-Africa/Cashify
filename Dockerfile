# nuke the cache to force a rebuild of the image
# this is useful when you change the requirements.txt file
ARG CACHEBUST=1

# use this image as the base
FROM python:3.13-slim

# set environment variables to prevent python from writing .pyc files and to flush stdout and stderr streams
# to the console (useful for debugging)
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# create a working directory in the container and cd into it
WORKDIR /bot

# Install ffmpeg
RUN apt-get update && \
    apt-get install -y ffmpeg && \
    rm -rf /var/lib/apt/lists/*

# copy and install dependencies to working directory
COPY requirements.txt requirements.txt
RUN pip3 install -r requirements.txt

# copy source code to working directory
COPY . .

# run the application using gunicorn
CMD sh -c "gunicorn -b 0.0.0.0:${PORT} app:app"

# expose the port the app runs on
EXPOSE ${PORT}
