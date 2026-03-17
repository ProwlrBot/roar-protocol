package roar

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"math"
	"sort"
	"strconv"
	"strings"
	"time"
)

// signingBody produces the canonical JSON body for HMAC signing.
//
// This must match the Python output of:
//
//	json.dumps({"id": ..., "from": ..., "to": ..., "intent": ...,
//	            "payload": ..., "context": ..., "timestamp": ...}, sort_keys=True)
//
// Python's default separators are ", " and ": " (with spaces).
// Float values like 1710000000.0 are rendered with a trailing ".0".
func signingBody(msg ROARMessage) []byte {
	ts, _ := msg.Auth["timestamp"]
	body := map[string]any{
		"id":        msg.ID,
		"from":      msg.FromIdentity.DID,
		"to":        msg.ToIdentity.DID,
		"intent":    string(msg.Intent),
		"payload":   msg.Payload,
		"context":   msg.Context,
		"timestamp": ts,
	}
	return []byte(canonicalJSON(body))
}

// canonicalJSON produces JSON matching Python's json.dumps(obj, sort_keys=True)
// with default separators (", " and ": ").
func canonicalJSON(v any) string {
	switch val := v.(type) {
	case nil:
		return "null"
	case bool:
		if val {
			return "true"
		}
		return "false"
	case string:
		return strconv.Quote(val)
	case int:
		return strconv.Itoa(val)
	case int64:
		return strconv.FormatInt(val, 10)
	case float64:
		return formatFloat(val)
	case []any:
		parts := make([]string, len(val))
		for i, item := range val {
			parts[i] = canonicalJSON(item)
		}
		return "[" + strings.Join(parts, ", ") + "]"
	case []string:
		parts := make([]string, len(val))
		for i, item := range val {
			parts[i] = strconv.Quote(item)
		}
		return "[" + strings.Join(parts, ", ") + "]"
	case map[string]any:
		keys := make([]string, 0, len(val))
		for k := range val {
			keys = append(keys, k)
		}
		sort.Strings(keys)
		parts := make([]string, len(keys))
		for i, k := range keys {
			parts[i] = strconv.Quote(k) + ": " + canonicalJSON(val[k])
		}
		return "{" + strings.Join(parts, ", ") + "}"
	default:
		// Fallback: use fmt for unknown types
		return fmt.Sprintf("%v", val)
	}
}

// formatFloat formats a float64 to match Python's json.dumps behavior.
// Python renders 1710000000.0 as "1710000000.0" (always has decimal point),
// and 1.5 as "1.5".
func formatFloat(f float64) string {
	if math.IsInf(f, 0) || math.IsNaN(f) {
		return "null" // JSON doesn't support Inf/NaN
	}

	// If the float is a whole number, Python renders it with ".0"
	if f == math.Trunc(f) && !math.IsInf(f, 0) {
		// Format as integer then append .0
		return strconv.FormatInt(int64(f), 10) + ".0"
	}

	// Otherwise, use standard float formatting
	return strconv.FormatFloat(f, 'f', -1, 64)
}

// SignMessage signs a ROARMessage with HMAC-SHA256.
// It sets msg.Auth["signature"] and msg.Auth["timestamp"].
func SignMessage(msg *ROARMessage, secret string) {
	now := float64(time.Now().UnixMilli()) / 1000.0
	msg.Auth = map[string]any{
		"timestamp": now,
	}
	body := signingBody(*msg)
	mac := hmac.New(sha256.New, []byte(secret))
	mac.Write(body)
	sig := hex.EncodeToString(mac.Sum(nil))
	msg.Auth["signature"] = "hmac-sha256:" + sig
}

// VerifyMessage verifies the HMAC-SHA256 signature on a ROARMessage.
// Returns true if the signature is valid.
func VerifyMessage(msg ROARMessage, secret string) bool {
	sigValue, ok := msg.Auth["signature"].(string)
	if !ok || !strings.HasPrefix(sigValue, "hmac-sha256:") {
		return false
	}

	expected := strings.TrimPrefix(sigValue, "hmac-sha256:")
	body := signingBody(msg)
	mac := hmac.New(sha256.New, []byte(secret))
	mac.Write(body)
	actual := hex.EncodeToString(mac.Sum(nil))

	return hmac.Equal([]byte(expected), []byte(actual))
}
