FROM gym-anything-local/seed-isolation:20260918
ARG USER_UID
ARG USER_GID
RUN groupmod -g ${USER_GID} experiment && usermod -u ${USER_UID} -g ${USER_GID} experiment
USER experiment
ENTRYPOINT []
