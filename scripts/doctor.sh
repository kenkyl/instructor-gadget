#!/usr/bin/env bash
# Health check for the local stack. Each check prints PASS/FAIL; exits non-zero if any fail.
set -uo pipefail

fails=0
pass() { printf "  \033[32mPASS\033[0m  %s\n" "$1"; }
fail() { printf "  \033[31mFAIL\033[0m  %s\n" "$1"; fails=$((fails + 1)); }

echo "Data stores"

if docker compose exec -T postgres pg_isready -U "${POSTGRES_USER:-instructor}" -d "${POSTGRES_DB:-instructor}" >/dev/null 2>&1; then
  pass "Postgres accepting connections"
else
  fail "Postgres not reachable (run: make up)"
fi

if [ "$(docker compose exec -T redis redis-cli PING 2>/dev/null | tr -d '\r')" = "PONG" ]; then
  pass "Redis responds to PING"
else
  fail "Redis not reachable (run: make up)"
fi

version=$(docker compose exec -T redis redis-cli INFO server 2>/dev/null | tr -d '\r' | awk -F: '/^redis_version/ {print $2}')
if [ "${version%%.*}" -ge 8 ] 2>/dev/null; then
  pass "Redis version $version (>= 8)"
else
  fail "Redis version '${version:-unknown}' is below 8"
fi

# FT._LIST lists search indexes. On a Redis without the Query Engine it's an unknown command.
ft=$(docker compose exec -T redis redis-cli FT._LIST 2>&1)
if echo "$ft" | grep -qi "ERR"; then
  fail "Query Engine missing: FT._LIST -> $ft"
else
  pass "Query Engine available (FT._LIST works; indexes: ${ft:-none})"
fi

exit "$fails"
