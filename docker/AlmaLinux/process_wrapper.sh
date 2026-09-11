#!/usr/bin/env bash
# A basic process wrapper which takes as first argument
# a path to a binary that is meant to be wrapped. Next it takes its own
# configs parameters up until an argument "--" after which all
# remaining arguments are passed on to the wrapped process as is.

TARGET_EXECUTABLE="$1"
shift 1

# Defaults
## How long to await in seconds between checking up on the wrapped process
POLL_TIME=3
## How long to sleep after the wrapped process has finished and before exiting ourselves
SLEEP_TIME=1
## At which verbosity to log
if [[ "$LOG_LEVEL" == "" ]]
then
  LOG_LEVEL="ERROR"
fi

# Logging functions logging is possible in both JSON and text based

function utc_now() {
  echo "$(date -u +%Y-%m-%dT"%T.%3N")"
}

function JSON_LOG() {
  LEVEL="$1"
  if [[ "${LEVEL}" == "DEBUG" ]]  && [[ "${LOG_LEVEL}" != "DEBUG" ]]
  then
    return
  fi
  MESSAGE="$2"
  shift 2

  EXTRA_FIELDS=""
  while (( "$#" ))
  do
    if [[ "$2" == "" ]]
    then
      LOG_WARNING "Bad log statement unmatched argument" "unmatched_key" "$1" "Original_message" "${MESSAGE}"
      break
    fi
    EXTRA_FIELDS="${EXTRA_FIELDS}, \"$1\": \"$2\""

    shift 2
  done

  echo "{\"ts\": \"`utc_now`\": \"levelname\": \"${LEVEL}\", \"message\": \"${MESSAGE}\", \"filename\": \"$0\", \"job_id\": \"$OPENEO_BATCH_JOB_ID\", \"user_id\": \"$OPENEO_USER_ID\"${EXTRA_FIELDS}}"
}

function TEXT_LOG() {
  LEVEL="$1"
  MESSAGE="$2"
  shift 2
  echo "${LEVEL}:`utc_now`:${MESSAGE} $@"
}

# By default LOG_DEBUG is a no-op
function LOG_DEBUG() {
  if [ "$LOG_LEVEL" == "DEBUG" ]
  then
    TEXT_LOG "DEBUG" "$@"
  fi
}

function LOG_INFO() {
  if [[ "$LOG_LEVEL" == "DEBUG" ]] || [[ "$LOG_LEVEL" == "INFO" ]]
  then
    TEXT_LOG "INFO" "$@"
  fi
}

function LOG_ERROR() {
  TEXT_LOG "ERROR" "$@"
  exit 1
}

# Process the arguments for the wrapper
ARGUMENT_DELIMITER_FOUND=false

while (( "$#" ))
do
  case "$1" in
    -o|--output-format) _LOG_FORMAT="$2"
                 shift 2
                 case "$_LOG_FORMAT" in
                   txt) LOG_DEBUG "Default is text log format keeping loggers"
                        ;;
                   json)
                          function LOG_DEBUG() {
                              if [ "$LOG_LEVEL" == "DEBUG" ]
                              then
                                JSON_LOG "DEBUG" "$@"
                              fi
                          }
                          function LOG_INFO() {
                              if [[ "$LOG_LEVEL" == "DEBUG" ]] || [[ "$LOG_LEVEL" == "INFO" ]]
                              then
                                JSON_LOG "INFO" "$@"
                              fi
                          }
                          function LOG_ERROR() {
                            JSON_LOG "ERROR" "$@"
                            exit 1
                          }

                 esac
                 ;;
    -l|--log-level) LOG_LEVEL="$(echo $2 | tr '[:lower:]' '[:upper:]')"
                shift 2
                LOG_DEBUG "Loglevel set via CLI" "LOG_LEVEL" "${LOG_LEVEL}"
                ;;
    -s|--sleep-seconds) SLEEP_TIME="$(echo $2 | grep "^[0-9][.0-9]*$")"
                if [[ "$SLEEP_TIME" != "$2" ]]
                then
                  LOG_ERROR "Sleep time must be number of seconds so a valid numeric value" "bad_value" "$2"
                fi
                shift 2
                LOG_DEBUG "Sleep time for after process finish set via CLI" "SLEEP_SECONDS" "$SLEEP_TIME"
                ;;
    -p|--poll-seconds) POLL_TIME="$(echo $2 | grep "^[0-9][.0-9]*$")"
                       if [[ "$POLL_TIME" != "$2" ]]
                       then
                         LOG_ERROR "Poll time must be number of seconds so a valid numeric value" "bad_value" "$2"
                       fi
                       shift 2
                       LOG_DEBUG "Poll time between checks of the wrapped process set via CLI" "POLL_SECONDS" "$POLL_TIME"
                       ;;
    --)     ARGUMENT_DELIMITER_FOUND=true
            shift
            break
            ;;

    *)      LOG_ERROR "Unsupported argument $1" "remaining args" "$@"
            ;;
  esac
done


# Start the wrapping logic

if [[ -x "$TARGET_EXECUTABLE" ]]
then
    LOG_INFO "Wrapping '$TARGET_EXECUTABLE'" "Args" "$@"
else
    LOG_ERROR "Cannot wrap '$TARGET_EXECUTABLE' since it is not a path to an executable file"
fi

#Started the wrapped process in the background and store it's PID
$TARGET_EXECUTABLE "$@" &
WRAPPED_PID="$!"

# Now that we know the PID of the wrapped process create a helper function
# to send signals to it

function send_signal_to_child() {
  SIGNAL_NUMBER="$1"

  kill -s ${SIGNAL_NUMBER} ${WRAPPED_PID} 2>/dev/null
}

# Install signal handlers for all signals that can be trapped
# SIGKIL (9) and SIGSTOP (19) cannot
for sig in `/bin/kill -l | /bin/sed -e 's/KILL\s//' -e 's/STOP\s//'`;
do
  #Installing signal sender ${sig}
  trap "send_signal_to_child ${sig}" ${sig} 2>/dev/null
done

# Sleep and wake up to not do blocked waiting
# Get the process ID and make sure no whitespace from ps output
while [ "$(ps -p ${WRAPPED_PID} -o pid= | tr -d ' ')" == "${WRAPPED_PID}" ]
do
  if [ "${LOG_LEVEL}" == "DEBUG" ]
  then
    LOG_DEBUG "Wrapped process still exists" "PID" "$WRAPPED_PID"
  fi
  sleep "$POLL_TIME"
done

# Blocking wait to get exit code
wait ${WRAPPED_PID}
STATUS="$?"

LOG_INFO "Wrapped process ended" "PID" "$WRAPPED_PID" "exit_code" "$STATUS"

sleep $SLEEP_TIME
exit ${STATUS}
