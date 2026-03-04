#!/usr/bin/env bash
set -o nounset
set -o pipefail

# ANSI colors
RESET="\033[0m"
BOLD="\033[1m"
DIM="\033[2m"
BLACK="\033[30m"
RED="\033[31m"
GREEN="\033[32m"
YELLOW="\033[33m"
BLUE="\033[34m"
MAGENTA="\033[35m"
CYAN="\033[36m"
WHITE="\033[37m"
BG_BLACK="\033[40m"
BG_GREEN="\033[42m"
BG_RED="\033[41m"
BG_YELLOW="\033[43m"
BG_BLUE="\033[44m"
BG_CYAN="\033[46m"
BG_MAGENTA="\033[45m"

tag_ok()     { printf "${BOLD}${BG_GREEN}${BLACK}  OK   ${RESET}"; }
tag_info()   { printf "${BOLD}${BG_BLUE}${WHITE} INFO  ${RESET}"; }
tag_warn()   { printf "${BOLD}${BG_YELLOW}${BLACK} WARN  ${RESET}"; }
tag_err()    { printf "${BOLD}${BG_RED}${WHITE} FAIL  ${RESET}"; }
tag_http()   { printf "${BOLD}${BG_BLACK}${WHITE} HTTP  ${RESET}"; }
tag_vec()    { printf "${BOLD}${BG_CYAN}${BLACK} VEC   ${RESET}"; }
tag_cors()   { printf "${BOLD}${BG_MAGENTA}${WHITE} CORS  ${RESET}"; }
tag_chunk()  { printf "${BOLD}${BG_BLUE}${WHITE} CHUNK ${RESET}"; }
tag_scrape() { printf "${BOLD}${BG_BLUE}${WHITE}SCRAPE ${RESET}"; }

status_color() {
  local status="$1"
  if [[ "$status" =~ ^2 ]]; then
    printf "${GREEN}%s${RESET}" "$status"
  elif [[ "$status" =~ ^3 ]]; then
    printf "${YELLOW}%s${RESET}" "$status"
  elif [[ "$status" =~ ^4 ]]; then
    printf "${YELLOW}%s${RESET}" "$status"
  else
    printf "${RED}%s${RESET}" "$status"
  fi
}

print_header() {
  local cmd_text
  cmd_text="$*"
  clear
  printf "\n"
  printf "${BOLD}${CYAN}============================================================${RESET}\n"
  printf "${BOLD}${WHITE} OmniCortex Pretty API Console ${RESET}${DIM}(live view)${RESET}\n"
  printf "${DIM} command: %s${RESET}\n" "$cmd_text"
  printf "${DIM} endpoint: http://localhost:8000${RESET}\n"
  printf "${BOLD}${CYAN}============================================================${RESET}\n\n"
}

emit() {
  local tag_func="$1"
  local text="$2"
  local line_ts="$3"
  if [[ -n "$line_ts" ]]; then
    printf "${DIM}${WHITE}%s${RESET} " "$line_ts"
  else
    printf "                    "
  fi
  "$tag_func"
  printf "  %b\n" "$text"
}

extract_ts() {
  local line="$1"
  if [[ "$line" =~ ^([0-9]{4}-[0-9]{2}-[0-9]{2}[[:space:]][0-9]{2}:[0-9]{2}:[0-9]{2}(,[0-9]{3})?) ]]; then
    printf "%s" "${BASH_REMATCH[1]}"
  else
    printf ""
  fi
}

pretty_stream() {
  while IFS= read -r line; do
    local_ts="$(extract_ts "$line")"
    lc="$(printf '%s' "$line" | tr '[:upper:]' '[:lower:]')"

    if [[ "$line" =~ \"([A-Z]+)[[:space:]]+([^[:space:]]+)[[:space:]]+HTTP/[0-9.]+\"[[:space:]]+([0-9]{3}) ]]; then
      method="${BASH_REMATCH[1]}"
      path="${BASH_REMATCH[2]}"
      status="${BASH_REMATCH[3]}"
      colored_status="$(status_color "$status")"
      emit tag_http "${BLUE}${method}${RESET} ${CYAN}${path}${RESET} ${colored_status}" "$local_ts"
      continue
    fi

    if [[ "$line" == *"PostgreSQL connected"* ]] || [[ "$line" == *"All dependencies validated"* ]] || [[ "$line" == *"Backend ready"* ]]; then
      emit tag_ok "$line" "$local_ts"
      continue
    fi

    if [[ "$line" == *"Startup Validation"* ]] || [[ "$line" == *"Application startup complete"* ]] || [[ "$line" == *"Started server process"* ]] || [[ "$line" == *"Uvicorn running on"* ]] || [[ "$line" == *"vLLM running"* ]]; then
      emit tag_info "$line" "$local_ts"
      continue
    fi

    if [[ "$line" == *"CORS Preflight"* ]] || [[ "$line" == *"CORS Blocked"* ]] || [[ "$line" == *"CORS Error"* ]]; then
      emit tag_cors "$line" "$local_ts"
      continue
    fi

    if [[ "$line" == *"Vector store created"* ]] || [[ "$line" == *"Deleted vector store"* ]]; then
      emit tag_vec "$line" "$local_ts"
      continue
    fi

    if [[ "$line" == *"Batch saved"* ]] || [[ "$line" == *"parent chunks"* ]] || [[ "$line" == *"children"* ]]; then
      emit tag_chunk "$line" "$local_ts"
      continue
    fi

    if [[ "$line" == *"Scraping "* ]] || [[ "$line" == *"Processing URLs"* ]] || [[ "$line" == *"URL processing completed"* ]]; then
      emit tag_scrape "$line" "$local_ts"
      continue
    fi

    if [[ "$line" == *"Created agent:"* ]] || [[ "$line" == *"Deleted agent:"* ]] || [[ "$line" == *"Updated agent:"* ]]; then
      emit tag_ok "$line" "$local_ts"
      continue
    fi

    if [[ "$lc" == *"warning"* ]] || [[ "$line" == *"WARNING"* ]]; then
      emit tag_warn "$line" "$local_ts"
      continue
    fi

    if [[ "$lc" == *"error"* ]] || [[ "$lc" == *"traceback"* ]] || [[ "$lc" == *"exception"* ]]; then
      emit tag_err "$line" "$local_ts"
      continue
    fi

    emit tag_info "$line" "$local_ts"
  done
}

if [[ "$#" -gt 0 ]]; then
  CMD=("$@")
else
  CMD=("uv" "run" "python" "api.py")
fi

print_header "${CMD[@]}"
"${CMD[@]}" 2>&1 | pretty_stream
exit "${PIPESTATUS[0]}"
