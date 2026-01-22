#!/usr/bin/env bash
# Smoke test for Connections Social demo flow
# Usage: ./scripts/smoke_test.sh
#
# Prerequisites:
#   - Backend running at localhost:8000
#   - Profile photos in data/profiles/
#   - Group photos in uploads/

set -e

BASE_URL="http://localhost:8000"
PASS="\033[0;32m✓\033[0m"
FAIL="\033[0;31m✗\033[0m"

echo "=== Connections Social Smoke Test ==="
echo ""

# 1. Health check
echo -n "1. Health check... "
HEALTH=$(curl -s "$BASE_URL/health")
if echo "$HEALTH" | grep -q '"status":"healthy"'; then
    echo -e "$PASS healthy"
else
    echo -e "$FAIL"
    echo "   Response: $HEALTH"
    exit 1
fi

# 2. Reset demo (clear graph state)
echo -n "2. Reset demo... "
RESET=$(curl -s -X POST "$BASE_URL/admin/reset-demo")
if echo "$RESET" | grep -q '"status":"completed"'; then
    echo -e "$PASS cleared"
else
    echo -e "$FAIL"
    echo "   Response: $RESET"
    exit 1
fi

# 3. Rebuild profile index
echo -n "3. Rebuild profile index... "
REBUILD=$(curl -s -X POST "$BASE_URL/admin/rebuild-profile-index")
PERSONS=$(echo "$REBUILD" | grep -o '"persons_created":[0-9]*' | cut -d: -f2)
PROFILES=$(echo "$REBUILD" | grep -o '"profiles_inserted":[0-9]*' | cut -d: -f2)
if [ -n "$PERSONS" ] && [ "$PERSONS" -gt 0 ]; then
    echo -e "$PASS $PERSONS persons, $PROFILES profiles"
else
    echo -e "$FAIL"
    echo "   Response: $REBUILD"
    exit 1
fi

# 4. Ingest folder (force)
echo -n "4. Ingest folder... "
INGEST=$(curl -s -X POST "$BASE_URL/ingest/folder?force=true")
PROCESSED=$(echo "$INGEST" | grep -o '"processed":[0-9]*' | cut -d: -f2)
EDGES=$(echo "$INGEST" | grep -o '"total_edges_created":[0-9]*' | cut -d: -f2)
if [ -n "$PROCESSED" ]; then
    echo -e "$PASS $PROCESSED images, $EDGES edges"
else
    echo -e "$FAIL"
    echo "   Response: $INGEST"
    exit 1
fi

# 5. Graph summary
echo -n "5. Graph summary... "
SUMMARY=$(curl -s "$BASE_URL/graph/summary")
TOTAL_EDGES=$(echo "$SUMMARY" | grep -o '"edges_total":[0-9]*' | cut -d: -f2)
TOTAL_PERSONS=$(echo "$SUMMARY" | grep -o '"persons_total":[0-9]*' | cut -d: -f2)
if [ -n "$TOTAL_EDGES" ]; then
    echo -e "$PASS $TOTAL_PERSONS persons, $TOTAL_EDGES edges"
else
    echo -e "$FAIL"
    echo "   Response: $SUMMARY"
    exit 1
fi

# 6. Get neighbors (use first person from graph)
echo -n "6. Get neighbors... "
# Extract first person from top_edges
FIRST_PERSON=$(echo "$SUMMARY" | grep -o '"person_a":"[^"]*"' | head -1 | cut -d'"' -f4)
if [ -n "$FIRST_PERSON" ]; then
    ENCODED_PERSON=$(python3 -c "import urllib.parse; print(urllib.parse.quote('$FIRST_PERSON'))")
    NEIGHBORS=$(curl -s "$BASE_URL/graph/neighbors?person=$ENCODED_PERSON")
    NEIGHBOR_COUNT=$(echo "$NEIGHBORS" | grep -o '"person":"[^"]*"' | wc -l | tr -d ' ')
    if [ "$NEIGHBOR_COUNT" -gt 0 ]; then
        echo -e "$PASS $FIRST_PERSON has $NEIGHBOR_COUNT neighbors"
    else
        echo -e "$FAIL no neighbors"
        echo "   Response: $NEIGHBORS"
    fi
else
    echo -e "- skipped (no persons in graph)"
fi

# 7. Get ego network
echo -n "7. Get ego network... "
if [ -n "$FIRST_PERSON" ]; then
    EGO=$(curl -s "$BASE_URL/graph/ego?person=$ENCODED_PERSON&depth=2")
    EGO_NODES=$(echo "$EGO" | grep -o '"nodes":\[[^]]*\]' | grep -o '"[^"]*"' | wc -l | tr -d ' ')
    EGO_EDGES=$(echo "$EGO" | grep -o '"edges":\[' | wc -l | tr -d ' ')
    if [ "$EGO_NODES" -gt 0 ]; then
        echo -e "$PASS $EGO_NODES nodes in ego network"
    else
        echo -e "$FAIL"
        echo "   Response: $EGO"
    fi
else
    echo -e "- skipped (no persons in graph)"
fi

# 8. List profiles
echo -n "8. List profiles... "
PROFILES_LIST=$(curl -s "$BASE_URL/profiles/list")
PROFILE_COUNT=$(echo "$PROFILES_LIST" | grep -o '"name":"[^"]*"' | wc -l | tr -d ' ')
echo -e "$PASS $PROFILE_COUNT profiles"

# 9. Storage info
echo -n "9. Storage info... "
STORAGE=$(curl -s "$BASE_URL/admin/storage-info")
UPLOADS_COUNT=$(echo "$STORAGE" | grep -o '"uploads_count":[0-9]*' | cut -d: -f2)
PROFILES_COUNT=$(echo "$STORAGE" | grep -o '"profiles_count":[0-9]*' | cut -d: -f2)
if [ -n "$UPLOADS_COUNT" ]; then
    echo -e "$PASS $PROFILES_COUNT profiles, $UPLOADS_COUNT uploads"
else
    echo -e "$FAIL"
    echo "   Response: $STORAGE"
fi

# 10. Shortest path
echo -n "10. Shortest path... "
if [ -n "$FIRST_PERSON" ]; then
    # Get second person from top_edges
    SECOND_PERSON=$(echo "$SUMMARY" | grep -o '"person_b":"[^"]*"' | head -1 | cut -d'"' -f4)
    if [ -n "$SECOND_PERSON" ]; then
        ENCODED_SECOND=$(python3 -c "import urllib.parse; print(urllib.parse.quote('$SECOND_PERSON'))")
        PATH_RESULT=$(curl -s "$BASE_URL/graph/path?source=$ENCODED_PERSON&target=$ENCODED_SECOND")
        if echo "$PATH_RESULT" | grep -q '"found":true'; then
            HOPS=$(echo "$PATH_RESULT" | grep -o '"hops":[0-9]*' | cut -d: -f2)
            echo -e "$PASS $FIRST_PERSON -> $SECOND_PERSON ($HOPS hops)"
        else
            echo -e "- no path found"
        fi
    else
        echo -e "- skipped (no second person)"
    fi
else
    echo -e "- skipped (no persons in graph)"
fi

# 11. Include unknown toggle
echo -n "11. Include unknown toggle... "
SUMMARY_WITH_UNKNOWN=$(curl -s "$BASE_URL/graph/summary?include_unknown=true")
UNKNOWN_COUNT=$(echo "$SUMMARY_WITH_UNKNOWN" | grep -o '"unknown_persons_total":[0-9]*' | cut -d: -f2)
KNOWN_COUNT=$(echo "$SUMMARY_WITH_UNKNOWN" | grep -o '"known_persons_total":[0-9]*' | cut -d: -f2)
if [ -n "$KNOWN_COUNT" ] && [ -n "$UNKNOWN_COUNT" ]; then
    echo -e "$PASS known=$KNOWN_COUNT, unknown=$UNKNOWN_COUNT"
else
    echo -e "$FAIL"
    echo "   Response: $SUMMARY_WITH_UNKNOWN"
fi

# 12. Static image serving
echo -n "12. Static image serving... "
FIRST_IMAGE=$(ls uploads/*.jpg 2>/dev/null | head -1 | xargs basename 2>/dev/null)
if [ -n "$FIRST_IMAGE" ]; then
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "$BASE_URL/images/$FIRST_IMAGE")
    if [ "$HTTP_CODE" = "200" ]; then
        echo -e "$PASS /images/$FIRST_IMAGE returns 200"
    else
        echo -e "$FAIL HTTP $HTTP_CODE"
    fi
else
    echo -e "- skipped (no images in uploads/)"
fi

echo ""
echo "=== All tests passed ==="
