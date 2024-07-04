FROM python:3.9.19-bookworm

RUN apt update
RUN apt install micro nano curl htop bash -y

ENV SHELL /bin/bash

WORKDIR /home

COPY ./requirements.txt /home/requirements.txt
RUN pip install -Ur requirements.txt



CMD ["tail", "-f", "//dev/null"]