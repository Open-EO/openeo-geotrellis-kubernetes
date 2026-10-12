#!/usr/bin/env bash

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
# Make sure logs are redirected to the container's stdout and stderr.
# /proc/1/fd/1 is not usable here: tini (PID 1) is non-dumpable after the uid
# switch, so /proc/1/fd is root:root and unreadable/unwritable by the spark
# user. Write to a log file instead; entrypoint.sh tails it to stdout.
exec >> /opt/spark/work-dir/decom.log 2>&1
set +e

# log <level> <message> [extra json fields, each preceded by a comma]
log() {
  echo '{"message": "'"$2"'"'"$3"', "created": '"$(date +%s.%N)"', "levelname": "'"$1"'", "name": "decommission", "filename": "decom.sh", "job_id":"'"$OPENEO_BATCH_JOB_ID"'", "user_id":"'"$OPENEO_USER_ID"'"}'
}

log INFO "Asked to decommission"
# Find the pid to signal
WORKER_PID=$(ps -o pid,cmd -C java |grep Executor \
               | tail -n 1| awk '{ sub(/^[ \t]+/, ""); print }' \
               | cut -f 1 -d " ")

if [ -z "${WORKER_PID}" ]; then
  log WARNING "No executor JVM found, nothing to decommission"
  exit 0
fi

log DEBUG "Using worker pid $WORKER_PID"
START=$(date +%s)
# Tell entrypoint.sh to keep the container alive until we are done (see there).
touch /opt/spark/work-dir/decom.started
kill -s SIGPWR ${WORKER_PID}
KILL_STATUS=$?
# If the worker does exit stop blocking K8s cleanup. Note this is a "soft"
# block since the pod it's self will have a maximum decommissioning time which will
# overload this.
log DEBUG "Waiting for worker pid to exit"
tail --pid=${WORKER_PID} -f /dev/null
ELAPSED=$(( $(date +%s) - START ))

log INFO "Decommission done" ", \"kill exit status\": \"$KILL_STATUS\", \"elapsed\": \"${ELAPSED}s\""
touch /opt/spark/work-dir/decom.done
# Give the log tailer time to relay the line above before the wrapper exits.
sleep 1
