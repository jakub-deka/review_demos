FROM ollama/ollama

RUN apt update
RUN apt install micro nano curl htop bash -y

ENV SHELL /bin/bash

COPY ./init.sh /
RUN chmod +x /init.sh
RUN ./init.sh

ENTRYPOINT ["/bin/ollama"]
CMD ["serve"]