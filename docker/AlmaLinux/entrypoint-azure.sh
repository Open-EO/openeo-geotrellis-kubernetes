#!/bin/bash
#
# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

set -e

: "${SPARK_HOME:?SPARK_HOME must identify the inherited Spark installation}"

myuid=$(id -u)
mygid=$(id -g)
if ! getent passwd "$myuid" >/dev/null; then
    if [ -w /etc/passwd ]; then
        echo "$myuid:x:$myuid:$mygid:${SPARK_USER_NAME:-anonymous uid}:$SPARK_HOME:/bin/false" >> /etc/passwd
    else
        echo "Container ENTRYPOINT cannot add passwd entry for UID $myuid" >&2
        exit 1
    fi
fi

SPARK_CLASSPATH="${SPARK_CLASSPATH:+$SPARK_CLASSPATH:}${SPARK_HOME}/jars/*"
readarray -t SPARK_EXECUTOR_JAVA_OPTS < <(
    env | sort -t_ -k4 -n | sed -n 's/^SPARK_JAVA_OPT_[0-9]*=//p'
)
if [ -n "${SPARK_EXTRA_CLASSPATH:-}" ]; then
    SPARK_CLASSPATH="$SPARK_CLASSPATH:$SPARK_EXTRA_CLASSPATH"
fi
if [ -n "${HADOOP_CONF_DIR:-}" ]; then
    SPARK_CLASSPATH="$HADOOP_CONF_DIR:$SPARK_CLASSPATH"
fi

# Spark's distribution supplies the Hadoop client JARs; no external Hadoop CLI is required.
export PYARROW_IGNORE_TIMEZONE=1

case "${1:-}" in
    driver)
        shift
        : "${SPARK_DRIVER_BIND_ADDRESS:?SPARK_DRIVER_BIND_ADDRESS is required for driver mode}"
        CMD=(
            "$SPARK_HOME/bin/spark-submit"
            --conf "spark.driver.bindAddress=$SPARK_DRIVER_BIND_ADDRESS"
            --conf spark.executor.extraClassPath=/opt/openeo-logging-static.jar:/opt/geotrellis-dependencies-static.jar
            --conf spark.driver.extraClassPath=/opt/openeo-logging-static.jar:/opt/geotrellis-dependencies-static.jar
            --deploy-mode client
            "$@"
        )
        ;;
    executor)
        shift
        : "${JAVA_HOME:?JAVA_HOME is required for executor mode}"
        : "${SPARK_EXECUTOR_MEMORY:?SPARK_EXECUTOR_MEMORY is required for executor mode}"
        : "${SPARK_DRIVER_URL:?SPARK_DRIVER_URL is required for executor mode}"
        : "${SPARK_EXECUTOR_ID:?SPARK_EXECUTOR_ID is required for executor mode}"
        : "${SPARK_EXECUTOR_CORES:?SPARK_EXECUTOR_CORES is required for executor mode}"
        : "${SPARK_APPLICATION_ID:?SPARK_APPLICATION_ID is required for executor mode}"
        : "${SPARK_EXECUTOR_POD_IP:?SPARK_EXECUTOR_POD_IP is required for executor mode}"
        CMD=(
            "$JAVA_HOME/bin/java"
            "${SPARK_EXECUTOR_JAVA_OPTS[@]}"
            "-Xms$SPARK_EXECUTOR_MEMORY"
            "-Xmx$SPARK_EXECUTOR_MEMORY"
            -cp "$SPARK_CLASSPATH${SPARK_DIST_CLASSPATH:+:$SPARK_DIST_CLASSPATH}"
            org.apache.spark.executor.CoarseGrainedExecutorBackend
            --driver-url "$SPARK_DRIVER_URL"
            --executor-id "$SPARK_EXECUTOR_ID"
            --cores "$SPARK_EXECUTOR_CORES"
            --app-id "$SPARK_APPLICATION_ID"
            --hostname "$SPARK_EXECUTOR_POD_IP"
        )
        ;;
    *)
        if [ "$#" -eq 0 ]; then
            echo "Expected driver, executor, or a command to execute" >&2
            exit 1
        fi
        CMD=("$@")
        ;;
esac

DECOM_LOG=/opt/spark/work-dir/decom.log
rm -f /opt/spark/work-dir/decom.started /opt/spark/work-dir/decom.done
touch "$DECOM_LOG"
tail -F "$DECOM_LOG" &

# Preserve executor decommission handling from the upstream entrypoint.
# shellcheck disable=SC2016 # Expanded by the child shell, not this shell.
exec /usr/bin/tini -s -g -- /bin/bash -c '
    "$@"; rc=$?
    if [ -f /opt/spark/work-dir/decom.started ]; then
        trap "exit $rc" TERM
        for i in $(seq 1 100); do
            [ -f /opt/spark/work-dir/decom.done ] && break
            sleep 0.1 & wait $!
        done
        sleep 5 & wait $!
    fi
    exit $rc' -- "${CMD[@]}"
