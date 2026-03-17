package roar

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
)

// Client is an HTTP client for sending ROAR messages.
type Client struct {
	Identity      AgentIdentity
	SigningSecret string
	HTTPClient    *http.Client
}

// NewClient creates a new ROAR client with the given identity and signing secret.
func NewClient(identity AgentIdentity, secret string) *Client {
	return &Client{
		Identity:      identity,
		SigningSecret: secret,
		HTTPClient:    &http.Client{},
	}
}

// Send sends a ROARMessage to the specified URL via HTTP POST to /roar/message.
// The message is signed before sending.
func (c *Client) Send(url string, msg ROARMessage) (ROARMessage, error) {
	SignMessage(&msg, c.SigningSecret)

	body, err := json.Marshal(msg)
	if err != nil {
		return ROARMessage{}, fmt.Errorf("roar: marshal message: %w", err)
	}

	endpoint := url + "/roar/message"
	req, err := http.NewRequest(http.MethodPost, endpoint, bytes.NewReader(body))
	if err != nil {
		return ROARMessage{}, fmt.Errorf("roar: create request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")

	resp, err := c.HTTPClient.Do(req)
	if err != nil {
		return ROARMessage{}, fmt.Errorf("roar: send request: %w", err)
	}
	defer resp.Body.Close()

	respBody, err := io.ReadAll(resp.Body)
	if err != nil {
		return ROARMessage{}, fmt.Errorf("roar: read response: %w", err)
	}

	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return ROARMessage{}, fmt.Errorf("roar: server returned %d: %s", resp.StatusCode, string(respBody))
	}

	var result ROARMessage
	if err := json.Unmarshal(respBody, &result); err != nil {
		return ROARMessage{}, fmt.Errorf("roar: unmarshal response: %w", err)
	}

	return result, nil
}

// Health calls GET /roar/health on the given base URL and returns the parsed response.
func (c *Client) Health(url string) (map[string]any, error) {
	endpoint := url + "/roar/health"
	resp, err := c.HTTPClient.Get(endpoint)
	if err != nil {
		return nil, fmt.Errorf("roar: health request: %w", err)
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("roar: read health response: %w", err)
	}

	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return nil, fmt.Errorf("roar: health returned %d: %s", resp.StatusCode, string(body))
	}

	var result map[string]any
	if err := json.Unmarshal(body, &result); err != nil {
		return nil, fmt.Errorf("roar: unmarshal health response: %w", err)
	}

	return result, nil
}
