#!/bin/bash

# Cashify Endpoint Testing Script
# Tests if the application endpoints are accessible

SERVER_URL="${1:-http://localhost:8000}"

echo "===== Cashify Endpoint Testing ====="
echo "Testing server: $SERVER_URL"
echo ""

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Test counter
PASSED=0
FAILED=0

# Function to test an endpoint
test_endpoint() {
    local method=$1
    local endpoint=$2
    local expected_code=$3
    local description=$4

    echo -n "Testing $description... "

    response=$(curl -s -o /dev/null -w "%{http_code}" -X $method "$SERVER_URL$endpoint" 2>/dev/null)

    if [ "$response" == "$expected_code" ]; then
        echo -e "${GREEN}✓ PASS${NC} (HTTP $response)"
        ((PASSED++))
    else
        echo -e "${RED}✗ FAIL${NC} (Expected HTTP $expected_code, got HTTP $response)"
        ((FAILED++))
    fi
}

# Function to test endpoint with data
test_endpoint_with_data() {
    local method=$1
    local endpoint=$2
    local data=$3
    local description=$4

    echo -n "Testing $description... "

    response=$(curl -s -o /dev/null -w "%{http_code}" -X $method \
        -H "Content-Type: application/json" \
        -d "$data" \
        "$SERVER_URL$endpoint" 2>/dev/null)

    # Accept any 2xx, 4xx response (not 5xx which indicates server error)
    if [[ "$response" =~ ^(2|4)[0-9]{2}$ ]]; then
        echo -e "${GREEN}✓ PASS${NC} (HTTP $response)"
        ((PASSED++))
    else
        echo -e "${RED}✗ FAIL${NC} (HTTP $response - Server Error)"
        ((FAILED++))
    fi
}

echo "1. Health Check Endpoints"
echo "-------------------------"
test_endpoint "GET" "/" "200" "Root health check"
echo ""

echo "2. Product Endpoints"
echo "--------------------"
test_endpoint "GET" "/products" "200" "Get all products"
test_endpoint_with_data "POST" "/products" '{"test":"data"}' "Create product (should validate)"
echo ""

echo "3. Fee Management Endpoints"
echo "---------------------------"
test_endpoint "GET" "/fees" "200" "Get fees"
echo ""

echo "4. Escrow Endpoints"
echo "-------------------"
test_endpoint_with_data "GET" "/escrow/buyer/test" "" "Get buyer escrows"
test_endpoint_with_data "GET" "/escrow/seller/test" "" "Get seller escrows"
echo ""

echo "5. Upload Endpoints (Structure Test)"
echo "-------------------------------------"
# These will likely fail with 400/422 but should not return 500
test_endpoint_with_data "POST" "/upload/tiktok" '{"test":"data"}' "TikTok upload endpoint"
test_endpoint_with_data "POST" "/upload/instagram" '{"test":"data"}' "Instagram upload endpoint"
test_endpoint_with_data "POST" "/upload/facebook" '{"test":"data"}' "Facebook upload endpoint"
echo ""

echo "6. Server Connectivity"
echo "----------------------"
if curl -s --connect-timeout 5 "$SERVER_URL" > /dev/null 2>&1; then
    echo -e "${GREEN}✓${NC} Server is reachable at $SERVER_URL"
    ((PASSED++))
else
    echo -e "${RED}✗${NC} Server is NOT reachable at $SERVER_URL"
    ((FAILED++))
fi
echo ""

echo "===== Test Summary ====="
echo -e "Passed: ${GREEN}$PASSED${NC}"
echo -e "Failed: ${RED}$FAILED${NC}"
echo "========================"

if [ $FAILED -eq 0 ]; then
    echo -e "${GREEN}All tests passed!${NC}"
    exit 0
else
    echo -e "${YELLOW}Some tests failed. Check the output above.${NC}"
    exit 1
fi
