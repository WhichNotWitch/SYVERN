# SYVERN Pilot server image.
#
# Default build ships the deterministic stub backend (PILOT_BACKEND=stub).
# For the real SysML v2 Pilot, build with --build-arg WITH_PILOT=1 AND make the
# Pilot artifact reachable to the build (it is not on Maven Central — populate a
# local Maven repo and mount it, e.g. `-v $HOME/.m2:/root/.m2`). See README.
#
#   docker build -t syvern-pilot .
#   docker run -p 8080:8080 -e PILOT_BACKEND=stub syvern-pilot

FROM gradle:8.7-jdk17 AS build
WORKDIR /src
COPY . .
ARG WITH_PILOT=
RUN gradle --no-daemon installDist $( [ -n "$WITH_PILOT" ] && echo "-PwithPilot" )

FROM eclipse-temurin:17-jre
WORKDIR /app
COPY --from=build /src/build/install/syvern-pilot-server/ /app/
ENV PILOT_PORT=8080 PILOT_THREADS=8 PILOT_BACKEND=stub
EXPOSE 8080
ENTRYPOINT ["/app/bin/syvern-pilot-server"]
