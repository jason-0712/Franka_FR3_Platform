ARG ROS_BASE=ros@sha256:a3f4de78e42cca693a543ece5798aedcf1cae0171fe71c334a047332cc72ef93
FROM ${ROS_BASE} AS dependencies
SHELL ["/bin/bash", "-c"]
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential cmake git python3-colcon-common-extensions python3-pip python3-venv \
      libconsole-bridge-dev libeigen3-dev libfmt-dev libpoco-dev libtinyxml2-dev \
      ros-humble-backward-ros ros-humble-generate-parameter-library \
      ros-humble-joint-state-publisher ros-humble-pinocchio=4.0.0-2jammy.20260606.100000 \
      ros-humble-moveit-core ros-humble-moveit-msgs \
      ros-humble-realtime-tools ros-humble-robot-state-publisher \
      ros-humble-ros2-control=2.54.3-1jammy.20261005.220306 \
      ros-humble-ros2-controllers=2.54.1-1jammy.20261005.222410 \
      ros-humble-rmw-cyclonedds-cpp ros-humble-xacro \
    && mkdir -p /opt/franka-image-manifest \
    && dpkg-query -W -f='${Package}\t${Version}\t${Architecture}\n' > /opt/franka-image-manifest/apt-packages.tsv \
    && rm -rf /var/lib/apt/lists/*

FROM dependencies AS native-build
ENV CMAKE_BUILD_PARALLEL_LEVEL=2 MAKEFLAGS=-j2
WORKDIR /build/franka_ws
COPY src/ src/
COPY SOURCE_BASELINE.json /opt/franka-image-manifest/SOURCE_BASELINE.json
COPY docker/build_control.sh /usr/local/bin/franka-build-control
RUN bash /usr/local/bin/franka-build-control

FROM dependencies AS runtime
ARG SOURCE_REVISION=unknown
ARG IMAGE_VERSION=0.1.0-preview
LABEL org.opencontainers.image.title="Franka FR3 Platform" \
      org.opencontainers.image.source="https://github.com/jason-0712/Franka_FR3_Platform" \
      org.opencontainers.image.revision="${SOURCE_REVISION}" \
      org.opencontainers.image.version="${IMAGE_VERSION}" \
      org.opencontainers.image.description="Model-independent FR3 platform; Mock and ROS read-only; real execute disabled"
COPY --from=native-build /opt/franka-control /opt/franka-control
COPY --from=native-build /opt/franka-image-manifest /opt/franka-image-manifest
COPY --from=native-build /build/franka_ws/src/libfranka/LICENSE /opt/franka-image-manifest/licenses/libfranka.LICENSE
COPY --from=native-build /build/franka_ws/src/libfranka/common/LICENSE /opt/franka-image-manifest/licenses/libfranka-common.LICENSE
COPY --from=native-build /build/franka_ws/src/franka_ros2/LICENSE /opt/franka-image-manifest/licenses/franka_ros2.LICENSE
COPY --from=native-build /build/franka_ws/src/franka_ros2/NOTICE /opt/franka-image-manifest/licenses/franka_ros2.NOTICE
COPY --from=native-build /build/franka_ws/src/franka_description/LICENSE /opt/franka-image-manifest/licenses/franka_description.LICENSE
COPY --from=native-build /build/franka_ws/src/franka_description/NOTICE /opt/franka-image-manifest/licenses/franka_description.NOTICE
COPY --from=native-build /build/franka_ws/src/crisp_controllers/package.xml /opt/franka-image-manifest/licenses/crisp_controllers.package.xml
COPY --from=native-build /build/franka_ws/src/franka_broadcasters/package.xml /opt/franka-image-manifest/licenses/franka_broadcasters.package.xml
COPY franka_platform/ /opt/franka-platform/franka_platform/
COPY scripts/franka_platform/ /opt/franka-platform/scripts/franka_platform/
COPY scripts/apply_nested_repo_patches.sh /opt/franka-platform/scripts/apply_nested_repo_patches.sh
COPY patches/ /opt/franka-platform/patches/
COPY SOURCE_BASELINE.json README.md THIRD_PARTY_NOTICES.md /opt/franka-platform/
COPY docs/franka_platform/ /opt/franka-platform/docs/franka_platform/
COPY docker/entrypoint.sh /usr/local/bin/franka-platform-entrypoint
COPY docker/healthcheck.py /usr/local/bin/franka-platform-healthcheck.py
COPY docker/python-wheels.lock.json /opt/franka-image-manifest/python-wheels.lock.json
COPY artifacts/franka_platform/docker/wheels/ /tmp/franka-wheels/
RUN python3 -m venv --system-site-packages /opt/franka-platform/venv \
    && /opt/franka-platform/venv/bin/python -m pip install --no-cache-dir --no-index --find-links /tmp/franka-wheels \
         -c /opt/franka-platform/franka_platform/constraints.txt websockets PyYAML setuptools wheel packaging \
    && /opt/franka-platform/venv/bin/python -m pip install --no-cache-dir --no-index --no-build-isolation --no-deps \
         /opt/franka-platform/franka_platform \
    && /opt/franka-platform/venv/bin/python -m pip check \
    && /opt/franka-platform/venv/bin/python -m pip freeze --all > /opt/franka-image-manifest/python-packages.txt \
    && rm -rf /tmp/franka-wheels \
    && useradd --create-home --uid 1000 --shell /bin/bash platform \
    && mkdir -p /home/platform/run/artifacts \
    && chown -R platform:platform /home/platform/run \
    && chmod 755 /usr/local/bin/franka-platform-entrypoint
ENV PATH=/opt/franka-platform/venv/bin:${PATH} \
    PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    ROS_LOG_DIR=/tmp/ros-log \
    ROS_DOMAIN_ID=30 RMW_IMPLEMENTATION=rmw_cyclonedds_cpp \
    FRANKA_PLATFORM_PYTHON=/opt/franka-platform/venv/bin/python \
    FRANKA_PLATFORM_CONFIG=/opt/franka-platform/franka_platform/configs/mock.yaml
USER platform
WORKDIR /home/platform/run
RUN /usr/local/bin/franka-platform-entrypoint self-test
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s \
    CMD ["/usr/local/bin/franka-platform-entrypoint", "python", "/usr/local/bin/franka-platform-healthcheck.py"]
ENTRYPOINT ["/usr/local/bin/franka-platform-entrypoint"]
CMD ["serve"]
