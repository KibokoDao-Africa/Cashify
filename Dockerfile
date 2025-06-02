# use this image as the base
FROM python:3.13-slim

# set environment variables to prevent python from writing .pyc files and to flush stdout and stderr streams
# to the console (useful for debugging)
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# create a working directory in the container and cd into it
WORKDIR /bot

# copy and install dependencies to working directory
COPY requirements.txt requirements.txt
RUN pip3 install -r requirements.txt

# copy source code to working directory
COPY . .

# run the bot
CMD ["gunicorn", "-b", "0.0.0.0:$PORT", "app:app"]
