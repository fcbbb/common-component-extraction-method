#!/bin/sh
# API-removal gate: the migrated artifact must not reference any Intel IPP
# symbol.  Scans the static library (or a shared object / executable) with
# nm and fails if an undefined or defined symbol matches any ipp* symbol (ipps*, ippi*, ippvm*, ippcore* and the ippMalloc/ippFree allocator).
#
# Usage: check_api_removal.sh <artifact> [<artifact> ...]
# Exit:  0 = clean, 1 = IPP symbols present, 2 = no artifact / bad usage.
set -eu

if [ $# -lt 1 ]; then
    echo "usage: $0 <artifact> [<artifact> ...]" >&2
    exit 2
fi

status=0
for art in "$@"; do
    if [ ! -f "$art" ]; then
        echo "missing artifact: $art" >&2
        exit 2
    fi
    hits=$(nm -g --defined-only "$art" 2>/dev/null | awk '{print $NF}' | grep -E '^ipp' || true)
    undef=$(nm -u "$art" 2>/dev/null | awk '{print $NF}' | grep -E '^ipp' || true)
    if [ -n "$hits" ] || [ -n "$undef" ]; then
        echo "FAIL $art: IPP symbols present"
        [ -n "$hits" ]  && echo "  defined:   $(echo "$hits"  | tr '\n' ' ')"
        [ -n "$undef" ] && echo "  undefined: $(echo "$undef" | tr '\n' ' ')"
        status=1
    else
        echo "OK   $art: no IPP symbols"
    fi
done

if [ "$status" -eq 0 ]; then
    echo "API_REMOVAL=PASS"
else
    echo "API_REMOVAL=FAIL"
fi
exit $status