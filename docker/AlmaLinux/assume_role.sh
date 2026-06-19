#!/usr/bin/env bash
# assume_role.sh
# Source this script to populate AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY,
# and AWS_SESSION_TOKEN via AssumeRoleWithWebIdentity.
#
# Required environment variables:
#   AWS_STS_ENDPOINT          e.g. https://sts.amazonaws.com
#   AWS_ROLE_ARN              e.g. arn:aws:iam::123456789012:role/MyRole
#   AWS_WEB_IDENTITY_TOKEN_FILE  path to the JWT token file
#
# Usage:
#   source assume_role.sh

# ---------------------------------------------------------------------------
# Logging helpers — all output goes to stderr; messages are JSON objects.
# Fields: timestamp, levelname, message
# ---------------------------------------------------------------------------
_ar_timestamp() { date -u +"%Y-%m-%dT%H:%M:%SZ"; }

_ar_log() {
  local level="$1"
  local message="$2"
  # Escape backslashes and double-quotes inside the message for valid JSON.
  local escaped_message
  escaped_message="$(printf '%s' "$message" | sed 's/\\/\\\\/g; s/"/\\"/g')"
  printf '{"timestamp":"%s","levelname":"%s","message":"%s"}\n' \
    "$(_ar_timestamp)" "$level" "$escaped_message" >&2
}

_ar_debug()   { _ar_log "DEBUG"   "$*"; }
_ar_info()    { _ar_log "INFO"    "$*"; }
_ar_warning() { _ar_log "WARNING" "$*"; }
_ar_error()   { _ar_log "ERROR"   "$*"; }

# ---------------------------------------------------------------------------
# URL-encode a string (RFC 3986 — encodes everything except A-Z a-z 0-9 - _ . ~)
# Requires python3 to be available.
# ---------------------------------------------------------------------------
_ar_urlencode() {
  local raw="$1"
  python3 -c "import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1], safe=''), end='')" "$raw"
}

# ---------------------------------------------------------------------------
# Main logic — wrapped in a function so 'return' works correctly whether
# the file is sourced or (accidentally) executed directly.
# ---------------------------------------------------------------------------
_ar_main() {

  # -------------------------------------------------------------------------
  # 1. Early exit if credentials are already present.
  # -------------------------------------------------------------------------
  if [[ -n "${AWS_ACCESS_KEY_ID:-}" && -n "${AWS_SECRET_ACCESS_KEY:-}" ]]; then
    _ar_debug "AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY already set; skipping role assumption."
    return 0
  fi

  # -------------------------------------------------------------------------
  # 2. Validate required environment variables.
  # -------------------------------------------------------------------------
  local missing=()
  [[ -z "${AWS_STS_ENDPOINT:-}"           ]] && missing+=("AWS_STS_ENDPOINT")
  [[ -z "${AWS_ROLE_ARN:-}"               ]] && missing+=("AWS_ROLE_ARN")
  [[ -z "${AWS_WEB_IDENTITY_TOKEN_FILE:-}" ]] && missing+=("AWS_WEB_IDENTITY_TOKEN_FILE")

  if [[ ${#missing[@]} -gt 0 ]]; then
    _ar_error "Missing required environment variable(s): ${missing[*]}"
    return 1
  fi

  if [[ ! -f "${AWS_WEB_IDENTITY_TOKEN_FILE}" ]]; then
    _ar_error "Token file not found: ${AWS_WEB_IDENTITY_TOKEN_FILE}"
    return 1
  fi

  # -------------------------------------------------------------------------
  # 3. Read and URL-encode the web identity token.
  # -------------------------------------------------------------------------
  local token
  token="$(<"${AWS_WEB_IDENTITY_TOKEN_FILE}")"
  if [[ -z "$token" ]]; then
    _ar_error "Token file is empty: ${AWS_WEB_IDENTITY_TOKEN_FILE}"
    return 1
  fi

  local encoded_token
  encoded_token="$(_ar_urlencode "$token")"
  _ar_debug "Web identity token read and URL-encoded (raw length: ${#token})."

  local encoded_role_arn
  encoded_role_arn="$(_ar_urlencode "${AWS_ROLE_ARN}")"

  # -------------------------------------------------------------------------
  # 4. Build POST body.
  # -------------------------------------------------------------------------
  local post_body
  post_body="Action=AssumeRoleWithWebIdentity"
  post_body+="&RoleSessionName=gdalProxy"
  post_body+="&Version=2011-06-15"
  post_body+="&RoleArn=${encoded_role_arn}"
  post_body+="&WebIdentityToken=${encoded_token}"
  post_body+="&DurationSeconds=43200"

  # -------------------------------------------------------------------------
  # 5. HTTP call with retry + exponential backoff + jitter.
  # -------------------------------------------------------------------------
  local max_attempts=5
  local attempt=0
  local base_delay=1      # seconds
  local connect_timeout=1 # seconds
  local max_time=5        # seconds per request

  local http_code response_body response
  local delay jitter

  while (( attempt < max_attempts )); do
    # Must us pre-increment; a post-increment won't play nice with set -e and exit with code 1 if attempt is 0
    (( ++attempt ))
    _ar_info "STS AssumeRoleWithWebIdentity attempt ${attempt}/${max_attempts}."

    # curl writes the body to stdout and the HTTP status code to the last line.
    # We capture both by appending the status code via -w.
    # Because we likely run with -e we should avoid failing on curl errors so we use || to never fail
    # and we track the exit code if there is a failure
    local curl_exit=0
    response="$(
      curl \
        --silent \
        --show-error \
        --connect-timeout "${connect_timeout}" \
        --max-time "${max_time}" \
        --request POST \
        --header "Content-Type: application/x-www-form-urlencoded" \
        --data "${post_body}" \
        --write-out "\n%{http_code}" \
        "${AWS_STS_ENDPOINT}" 2>&1
    )" || curl_exit=$?

    # Split body and status code (last line).
    http_code="$(printf '%s' "$response" | tail -n1)"
    response_body="$(printf '%s' "$response" | sed '$d')"

    if (( curl_exit != 0 )); then
      _ar_warning "curl failed (exit ${curl_exit}) on attempt ${attempt}."
    else
      _ar_debug "HTTP status ${http_code} received on attempt ${attempt}."
    fi

    # Success path.
    if [[ "$http_code" == "200" ]]; then
      _ar_info "STS request succeeded (HTTP 200)."
      break
    fi

    # Determine whether to retry.
    local should_retry=false
    if (( curl_exit != 0 )); then
      should_retry=true
    elif [[ "$http_code" == "429" ]] || [[ "$http_code" =~ ^5 ]]; then
      should_retry=true
    fi

    if [[ "$should_retry" == "true" ]] && (( attempt < max_attempts )); then
      # Exponential backoff: base_delay * 2^(attempt-1), capped at 60s.
      local shift_n=$(( attempt - 1 ))
      local delay_multiplier=$(( 1 << shift_n ))
      local exp_delay=$(( base_delay * delay_multiplier ))
      (( exp_delay > 60 )) && exp_delay=60
      # Jitter: random value in [0, exp_delay).
      jitter=$(( RANDOM % (exp_delay + 1) ))
      delay=$(( exp_delay + jitter ))
      _ar_warning "Retryable response (HTTP ${http_code}). Backing off for ${delay}s (exp=${exp_delay}s, jitter=${jitter}s)."
      sleep "${delay}"
    else
      # Non-retryable error or exhausted attempts.
      _ar_error "STS request failed after ${attempt} attempt(s). HTTP status: ${http_code}. Body: ${response_body}"
      return 1
    fi
  done

  if (( attempt == max_attempts )) && [[ "$http_code" != "200" ]]; then
    _ar_error "STS request failed after ${max_attempts} attempt(s). HTTP status: ${http_code}. Body: ${response_body}"
    return 1
  fi

  # -------------------------------------------------------------------------
  # 6. Parse XML response — no external XML parser required.
  # -------------------------------------------------------------------------
  _ar_debug "Parsing STS XML response."

  local access_key secret_key session_token

  access_key="$(printf '%s' "$response_body" \
    | grep -oP '(?<=<AccessKeyId>)[^<]+')"
  secret_key="$(printf '%s' "$response_body" \
    | grep -oP '(?<=<SecretAccessKey>)[^<]+')"
  session_token="$(printf '%s' "$response_body" \
    | grep -oP '(?<=<SessionToken>)[^<]+')"

  if [[ -z "$access_key" || -z "$secret_key" || -z "$session_token" ]]; then
    _ar_error "Failed to parse credentials from STS response. Body: ${response_body}"
    return 1
  fi

  # -------------------------------------------------------------------------
  # 7. Export credentials.
  # -------------------------------------------------------------------------
  export AWS_ACCESS_KEY_ID="$access_key"
  export AWS_SECRET_ACCESS_KEY="$secret_key"
  export AWS_SESSION_TOKEN="$session_token"

  _ar_info "AWS credentials set successfully (AccessKeyId: ${access_key:0:4}****)."
  return 0
}

_ar_main
