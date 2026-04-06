# nuke the cache to force a rebuild of the image
# this is useful when you change the requirements.txt file
ARG CACHEBUST=1

# use this image as the base - FULL image instead of slim for SSL support
FROM python:3.12

# set environment variables to prevent python from writing .pyc files and to flush stdout and stderr streams
# to the console (useful for debugging)
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# create a working directory in the container and cd into it
WORKDIR /bot

# Install ffmpeg and update CA certificates for MongoDB Atlas SSL
RUN apt-get update && \
    apt-get install -y ffmpeg ca-certificates libssl3 openssl && \
    update-ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# upgrade pip and install setuptools first
RUN pip3 install --upgrade pip setuptools wheel

# copy and install dependencies to working directory
COPY requirements.txt requirements.txt
RUN pip3 install --no-cache-dir -r requirements.txt

# copy source code to working directory
COPY . .

# set default port if not provided
ENV PORT=8000

# run the application using gunicorn
CMD sh -c "gunicorn -b 0.0.0.0:${PORT} app:app"

# expose the port the app runs on
EXPOSE ${PORT}
