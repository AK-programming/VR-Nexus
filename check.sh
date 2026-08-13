#!/usr/bin/env bash
# One-shot check that the Evidence Library is up and working end to end.
# Run from the project root:  ./check.sh
#
# Exits non-zero on the first failure, so it is also usable as a smoke test.
set -u

pass() { printf "  \033[32mOK\033[0m   %s\n" "$1"; }
fail() { printf "  \033[31mFAIL\033[0m %s\n" "$1"; exit 1; }

echo
echo "Evidence Library — status check"
echo

# 1. Containers. Nothing below can pass if these are not up, so check first and
#    report the count rather than dumping the whole table.
up=$(docker compose ps --services --filter status=running 2>/dev/null | wc -l | tr -d ' ')
[ "$up" = "5" ] && pass "containers running ($up/5)" \
  || fail "only $up/5 containers running — run: docker compose up -d"

# 2. API health. Reports degraded rather than erroring when a dependency is
#    down, so the body is what matters, not the status code.
health=$(curl -s --max-time 10 http://localhost:8000/health)
echo "$health" | grep -q '"status":"ok"' \
  && pass "api healthy" || fail "api unhealthy: $health"
echo "$health" | grep -q '"database":"ok"' \
  && pass "database reachable" || fail "database unreachable"

# 3. Embedding dimension. Must be 768 to match WBS 1.1.3 (Maryam's chunks
#    table); a mismatch here is silently wrong rather than loudly broken.
echo "$health" | grep -q '"embedding_dim":768' \
  && pass "embeddings 768-dim (matches WBS 1.1.3)" || fail "wrong embedding dim"

# 4. Generation. Optional by design — the pipeline runs on heuristics without it.
if echo "$health" | grep -q '"llm_available":true'; then
  pass "llm available (generation + auto-tagging on)"
else
  printf "  \033[33mnote\033[0m llm off — retrieval works, /ask will not generate\n"
fi

# 5. Indexed content, straight from Postgres.
docs=$(docker compose exec -T postgres psql -U evidence -d evidence_library -tAc \
  "select count(*) from documents where training_status='INDEXED';" 2>/dev/null | tr -d ' \r')
chunks=$(docker compose exec -T postgres psql -U evidence -d evidence_library -tAc \
  "select count(*) from chunks;" 2>/dev/null | tr -d ' \r')
if [ "${docs:-0}" -gt 0 ]; then
  pass "$docs indexed document(s), $chunks chunk(s)"
else
  printf "  \033[33mnote\033[0m no documents indexed yet — upload one in the UI\n"
  echo; echo "UI: http://localhost:8000/ui/"; echo; exit 0
fi

# 6. Retrieval. The actual Section 6 deliverable.
hits=$(curl -s --max-time 30 "http://localhost:8000/api/library/search?q=project%20approach&limit=3" \
  | python -c "import sys,json; print(len(json.load(sys.stdin)['hits']))" 2>/dev/null)
[ "${hits:-0}" -gt 0 ] && pass "search returned $hits hit(s)" \
  || fail "search returned nothing"

echo
echo "  UI    http://localhost:8000/ui/"
echo "  Docs  http://localhost:8000/docs"
echo
